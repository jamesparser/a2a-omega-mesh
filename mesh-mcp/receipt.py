"""Optional networkless receipt boundary. Stores signed bytes BEFORE permitting ack.
Does not call a model, execute instructions, start a poller, or send an ack.
Owner approval and a separate capability-limited executor are required for work.
"""
import hashlib
import re
import sqlite3
import time
from pathlib import Path
from board import BOARD, LIFETIME, MAX_BODY, MAX_MESSAGE_TTL, MAX_WIRE, RETENTION, SKEW, Verifier, canonical, uid


class Receipts:
    def __init__(self, path, principal, roster, clock=time.time):
        self.path, self.principal, self.clock = str(path), principal, clock
        self.roster = roster
        self.verifier = Verifier(roster)
        self.roster_digest = hashlib.sha256(canonical(roster)).hexdigest()
        if principal not in roster:
            raise ValueError('recipient')
        d = self.db()
        try:
            with d:
                d.executescript('''CREATE TABLE IF NOT EXISTS local_meta(k TEXT PRIMARY KEY,v TEXT);
                CREATE TABLE IF NOT EXISTS received(id TEXT PRIMARY KEY,digest TEXT,wire TEXT,expires INTEGER);''')
                old = dict(d.execute('SELECT k,v FROM local_meta'))
                if old:
                    if old.get('principal') != principal or old.get('roster') != self.roster_digest:
                        raise ValueError('receipt identity mismatch')
                else:
                    d.executemany('INSERT INTO local_meta VALUES(?,?)', [('principal', principal), ('roster', self.roster_digest), ('highwater', '0')])
        finally:
            d.close()
        Path(self.path).chmod(0o600)

    def db(self):
        d = sqlite3.connect(self.path, timeout=3)
        d.execute('PRAGMA synchronous=FULL')
        d.execute('PRAGMA secure_delete=ON')
        d.execute('PRAGMA max_page_count=4096')
        return d

    def accept(self, wire):
        if not isinstance(wire, dict) or set(wire) != {'envelope', 'signature'} or len(canonical(wire)) > MAX_WIRE:
            raise ValueError('signed wire')
        e = wire['envelope']
        if not isinstance(e, dict) or set(e) != {'v', 'board', 'principal', 'id', 'issued', 'expires', 'op', 'payload'}:
            raise ValueError('schema')
        p = e['principal']
        if type(e['v']) is not int or e['v'] != 2 or e['board'] != BOARD or e['op'] != 'post' or not uid(e['id']) or not isinstance(p, str) or p not in self.roster:
            raise ValueError('identity')
        payload = e['payload']
        if not isinstance(payload, dict) or set(payload) != {'to', 'kind', 'parent', 'body', 'ttl', 'dedupe'} or payload['to'] != self.principal or self.principal not in self.roster[p]['recipients']:
            raise ValueError('recipient acl')
        if payload['kind'] not in ('request', 'response') or (payload['kind'] == 'request' and payload['parent'] is not None) or (payload['kind'] == 'response' and not uid(payload['parent'])):
            raise ValueError('kind/parent')
        if payload['dedupe'] is not None and (not isinstance(payload['dedupe'], str) or not 1 <= len(payload['dedupe']) <= 64
                                              or not re.fullmatch(r'[A-Za-z0-9._:-]+', payload['dedupe'])):
            raise ValueError('dedupe key')
        if not isinstance(payload['body'], str) or not 0 < len(payload['body'].encode()) <= MAX_BODY or type(payload['ttl']) is not int or not 1 <= payload['ttl'] <= MAX_MESSAGE_TTL:
            raise ValueError('content')
        if type(e['issued']) is not int or type(e['expires']) is not int or not 0 < e['expires'] - e['issued'] <= LIFETIME:
            raise ValueError('time schema')
        self.verifier.verify(p, canonical(e), wire['signature'])
        now = int(self.clock())
        # Delivery can outlive the RPC authorization window; signed message TTL is separate.
        if not now - MAX_MESSAGE_TTL <= e['issued'] <= now + SKEW or e['issued'] + payload['ttl'] <= now:
            raise ValueError('delivery expiry')
        digest = hashlib.sha256(canonical(e)).hexdigest()
        d = self.db()
        try:
            with d:
                d.execute('BEGIN IMMEDIATE')
                if now < int(d.execute("SELECT v FROM local_meta WHERE k='highwater'").fetchone()[0]):
                    raise ValueError('receipt clock rollback')
                d.execute("UPDATE local_meta SET v=? WHERE k='highwater'", (str(now),))
                d.execute('DELETE FROM received WHERE expires+?<=?', (RETENTION, now))
                old = d.execute('SELECT digest FROM received WHERE id=?', (e['id'],)).fetchone()
                if old and old[0] != digest:
                    raise ValueError('receipt id conflict')
                if not old:
                    if d.execute('SELECT count(*) FROM received').fetchone()[0] >= 128:
                        raise ValueError('receipt capacity')
                    d.execute('INSERT INTO received VALUES(?,?,?,?)', (e['id'], digest, canonical(wire).decode(), e['issued'] + payload['ttl']))
        finally:
            d.close()
        return {'id': e['id'], 'trust': 'untrusted-data', 'state': 'durably-stored-not-executed'}

    def ack_payload(self, mid):
        d = self.db()
        try:
            if not d.execute('SELECT 1 FROM received WHERE id=?', (mid,)).fetchone():
                raise ValueError('no durable receipt; do not ack')
        finally:
            d.close()
        return {'id': mid}
