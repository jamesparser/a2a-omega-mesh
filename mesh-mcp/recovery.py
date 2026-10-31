"""Offline local snapshots, bounded inventory, quarantined restore; no activation API.
Private trusted directories only. Unencrypted: NOT an off-host disaster recovery plan.
Manifest detects accidental corruption, NOT hostile root/backup tampering.
"""
import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from board import APP_ID, BOARD, SCHEMA_VERSION, canonical, decode


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def valid(path, first=False):
    if not path.is_file() or path.is_symlink():
        raise ValueError('existing regular database required')
    d = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if d.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('integrity')
        if d.execute('PRAGMA application_id').fetchone()[0] != APP_ID or d.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise ValueError('schema')
        if first and d.execute('PRAGMA journal_mode').fetchone()[0] not in ('delete', 'wal'):
            raise ValueError('unknown journal mode')
        meta = dict(d.execute('SELECT k,v FROM meta'))
        if meta.get('board') != BOARD:
            raise ValueError('board')
        for table in ('messages', 'receipts', 'quotas'):
            d.execute('SELECT * FROM ' + table + ' LIMIT 0')
        return meta
    finally:
        d.close()


def copydb(source, dest):
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=3)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst, pages=64, sleep=.05)
    finally:
        dst.close()
        src.close()
    with dest.open('rb') as f:
        os.fsync(f.fileno())
    syncdir(dest.parent)


def snapshot(source, directory):
    source = Path(source).absolute()
    directory = Path(directory).absolute()
    # No following an untrusted writable directory. Caller owns all ancestors.
    if not directory.is_dir() or directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError('private backup directory required')
    # Serialized operator-only API; no concurrent backup writers supported.
    if len(list(directory.iterdir())) >= 8:
        raise ValueError('four-backup inventory full; operator retention required')
    valid(source, first=True)
    dest = directory / (str(uuid.uuid4()) + '.sqlite')
    manifest = Path(str(dest) + '.json')
    try:
        copydb(source, dest)
        meta = valid(dest)
        data = {'v': 1, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
                'bytes': dest.stat().st_size, 'board': BOARD, 'highwater': meta['highwater'],
                'roster': meta['roster']}
        fd = os.open(manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(canonical(data))
            f.flush()
            os.fsync(f.fileno())
        syncdir(directory)
        return dest
    except BaseException:
        dest.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def restore(source, destination):
    source, dest = Path(source).absolute(), Path(destination).absolute()
    meta = valid(source)
    m = decode(Path(str(source) + '.json').read_bytes())
    if m != {'v': 1, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
             'bytes': source.stat().st_size, 'board': BOARD, 'highwater': meta['highwater'], 'roster': meta['roster']}:
        raise ValueError('snapshot manifest mismatch')
    # Exclusive destination; existing state must never be overwritten.
    created = False
    try:
        if dest.exists() or dest.is_symlink():
            raise ValueError('destination exists')
        copydb(source, dest)
        created = True
        with sqlite3.connect(dest) as d:
            d.execute('PRAGMA synchronous=FULL')
            d.execute("UPDATE meta SET v='1' WHERE k='recovery_hold'")
        valid(dest)
        with dest.open('rb') as f:
            os.fsync(f.fileno())
        syncdir(dest.parent)
        return dest
    except BaseException:
        if created:
            dest.unlink(missing_ok=True)
        raise
