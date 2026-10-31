"""Isolated signed board v2; NO native-channel, model, provider or shell execution.
All signed bodies remain UNTRUSTED DATA. Requires trusted private state directory.
New database only; deliberately incompatible with the bearer pilot schema.
"""
import base64
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

NAMESPACE = 'mesh-board-prod-v2'
BOARD = 'omega-mesh-prod-20261031'
APP_ID = 1297302067
# Production cutover (2026-10-31): rev P schema v4 = lane-split quotas (rev B)
# + semantic per-message dedupe keys. Rev A/B databases (user_version=2/3) are
# refused; there is no migration and no bearer path.
SCHEMA_VERSION = 4
LIFETIME = 120
SKEW = 5
MAX_WIRE = 24576
MAX_BODY = 8192
MAX_MESSAGE_TTL = 3600
RETENTION = 300
NAME = re.compile(r'^[a-z][a-z0-9-]{0,31}$')


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ValueError('duplicate key')
        out[k] = v
    return out


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def uid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


class Verifier:
    """No private keys; exact principal, public key, namespace and canonical bytes."""
    def __init__(self, roster):
        self.roster = roster

    def verify(self, principal, data, signature):
        # Bounded inline path (input= works for any bytes; no fileno needed).
        self._run_ssh_verify(principal, data, signature)

    def verify_file(self, principal, data_path, signature):
        # Review fix (2026-10-30): a missing/unreadable data file must surface
        # as ValueError, not an unhandled OSError/AttributeError.
        try:
            data = data_path.read_bytes()
        except OSError:
            raise ValueError('signature data unreadable')
        self._run_ssh_verify(principal, data, signature)

    def _run_ssh_verify(self, principal, data, signature):
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError('signature data type')
        if not isinstance(signature, str) or not 1 <= len(signature) <= 4096:
            raise ValueError('signature required')
        try:
            sig = base64.b64decode(signature, validate=True)
        except (ValueError, UnicodeError):
            raise ValueError('signature encoding')
        with tempfile.TemporaryDirectory(prefix='verify-') as root:
            p = Path(root)
            (p / 'signers').write_text(principal + ' ' + self.roster[principal]['key'] + '\n')
            (p / 'sig').write_bytes(sig)
            try:
                r = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', str(p / 'signers'),
                                    '-I', principal, '-n', NAMESPACE, '-s', str(p / 'sig')],
                                   input=bytes(data), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=2, env={'PATH': '/usr/bin:/bin', 'HOME': root})
            except FileNotFoundError:
                raise ValueError('ssh-keygen unavailable')
            if r.returncode:
                raise ValueError('invalid signature')


class Store:
    def __init__(self, path, roster, clock=time.time):
        self.path = str(path)
        self.roster = roster
        self.clock = clock
        if not isinstance(roster, dict) or not 2 <= len(roster) <= 16:
            raise ValueError('roster')
        keys = set()
        for name, peer in roster.items():
            if not NAME.fullmatch(name) or set(peer) != {'key', 'recipients', 'rows', 'rate'}:
                raise ValueError('roster schema')
            if not isinstance(peer['key'], str) or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}', peer['key']) or peer['key'] in keys:
                raise ValueError('unique ed25519 keys required')
            keys.add(peer['key'])
            if not isinstance(peer['recipients'], list) or any(x not in roster or x == name for x in peer['recipients']):
                raise ValueError('acl')
            if type(peer['rows']) is not int or not 2 <= peer['rows'] <= 32:
                raise ValueError('rows')
            if type(peer['rate']) is not int or not 4 <= peer['rate'] <= 10:
                raise ValueError('rate')
        self.verifier = Verifier(roster)
        self.roster_digest = hashlib.sha256(canonical(roster)).hexdigest()
        try:
            self._init_state()
        except sqlite3.DatabaseError as ex:
            # Review fix (2026-10-30): a non-SQLite file must surface as
            # ValueError, never a raw sqlite3.DatabaseError.
            raise ValueError('database unreadable: ' + str(ex))

    def _init_state(self):
        # A non-SQLite file fails right here on the first read (review fix,
        # 2026-10-30): sqlite3.DatabaseError propagates to __init__, which wraps
        # it as ValueError so callers never see a raw sqlite3 error type.
        with self.db() as d:
            tables = d.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables:
                self.check(d)
            else:
                d.executescript('''PRAGMA application_id=1297302067;
                PRAGMA user_version=4;
                CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
                CREATE TABLE receipts(principal TEXT,id TEXT,digest TEXT,expires INTEGER,result TEXT,
                    PRIMARY KEY(principal,id));
                CREATE TABLE messages(id TEXT PRIMARY KEY,sender TEXT,recipient TEXT,kind TEXT,
                    parent TEXT,expires INTEGER,wire TEXT,acked INTEGER NOT NULL DEFAULT 0,
                    dedupe TEXT);
                CREATE UNIQUE INDEX terminal_once ON messages(parent) WHERE kind='response';
                CREATE INDEX inbox ON messages(recipient,acked,expires);
                CREATE INDEX dedupe ON messages(sender,recipient,dedupe,kind);
                CREATE TABLE quotas(principal TEXT,bucket INTEGER,lane TEXT NOT NULL DEFAULT 'data',n INTEGER,
                    PRIMARY KEY(principal,bucket,lane));
                ''')
                d.executemany('INSERT INTO meta VALUES(?,?)', [('board', BOARD), ('roster', self.roster_digest),
                              ('highwater', '0'), ('recovery_hold', '0')])
            os.chmod(self.path, 0o600)

    def check(self, d):
        if d.execute('PRAGMA application_id').fetchone()[0] != APP_ID or d.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise ValueError('wrong database; no legacy migration')
        meta = dict(d.execute('SELECT k,v FROM meta'))
        if meta.get('board') != BOARD or meta.get('roster') != self.roster_digest:
            raise ValueError('board/roster mismatch; offline review required')

    @contextmanager
    def db(self):
        d = sqlite3.connect(self.path, timeout=3)
        try:
            d.execute('PRAGMA synchronous=FULL')
            d.execute('PRAGMA secure_delete=ON')
            d.execute('PRAGMA journal_mode=DELETE')
            d.execute('PRAGMA max_page_count=16384')  # 64 MiB at default page size
            d.execute('PRAGMA busy_timeout=3000')
            with d:
                yield d
        finally:
            d.close()

    def housekeeping(self, d, now):
        meta = dict(d.execute('SELECT k,v FROM meta'))
        if meta['recovery_hold'] != '0':
            raise ValueError('restore quarantined; reconciliation required')
        # Strict rollback hold, not a tolerance that permits resurrecting pruned replays.
        if now < int(meta['highwater']):
            raise ValueError('clock rollback hold')
        d.execute("UPDATE meta SET v=? WHERE k='highwater'", (str(now),))
        d.execute('DELETE FROM receipts WHERE expires<=?', (now,))
        d.execute('DELETE FROM messages WHERE expires+?<=?', (RETENTION, now))
        d.execute('DELETE FROM quotas WHERE bucket<?', (now // 60,))

    def prune(self):
        with self.db() as d:
            d.execute('BEGIN IMMEDIATE')
            self.housekeeping(d, int(self.clock()))

    def rpc(self, wire):
        if not isinstance(wire, dict) or set(wire) != {'envelope', 'signature'}:
            raise ValueError('signed wrapper required')
        e = wire['envelope']
        fields = {'v', 'board', 'principal', 'id', 'issued', 'expires', 'op', 'payload'}
        if not isinstance(e, dict) or set(e) != fields:
            raise ValueError('envelope schema')
        p = e['principal']
        if not isinstance(p, str) or p not in self.roster or type(e['v']) is not int or e['v'] != 2 or e['board'] != BOARD or not uid(e['id']):
            raise ValueError('identity/audience')
        now = int(self.clock())
        if type(e['issued']) is not int or type(e['expires']) is not int or not now < e['expires'] <= e['issued'] + LIFETIME or not now - LIFETIME <= e['issued'] <= now + SKEW:
            raise ValueError('freshness')
        if e['expires'] <= e['issued'] or e['op'] not in ('post', 'inbox', 'ack'):
            raise ValueError('operation')
        data = canonical(e)
        if len(canonical(wire)) > MAX_WIRE:
            raise ValueError('wire limit')
        self.verifier.verify(p, data, wire['signature'])
        digest = hashlib.sha256(data).hexdigest()
        with self.db() as d:
            d.execute('BEGIN IMMEDIATE')
            now = int(self.clock())
            if not now < e['expires'] or e['issued'] > now + SKEW:
                raise ValueError('expired while verifying')
            self.housekeeping(d, now)
            old = d.execute('SELECT digest,result FROM receipts WHERE principal=? AND id=?', (p, e['id'])).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError('id conflict')
                return {'duplicate': True, 'result': decode(old[1]), 'trust': 'untrusted-data'}
            bucket = now // 60
            rate = self.roster[p]['rate']
            # Control ops (ack, response posts) count against their own lane so
            # data traffic can never consume the ack/response headroom (rev B).
            control = e['op'] == 'ack' or (e['op'] == 'post' and isinstance(e['payload'], dict) and e['payload'].get('kind') == 'response')
            lane = 'control' if control else 'data'
            limit = rate if control else rate - max(1, rate // 4)
            n = d.execute('SELECT n FROM quotas WHERE principal=? AND bucket=? AND lane=?', (p, bucket, lane)).fetchone()
            if n and n[0] >= limit:
                raise ValueError('principal rate quota')
            result = self.apply(d, p, e, wire, now)
            d.execute("INSERT INTO quotas VALUES(?,?,?,1) ON CONFLICT(principal,bucket,lane) DO UPDATE SET n=n+1", (p, bucket, lane))
            d.execute('INSERT INTO receipts VALUES(?,?,?,?,?)', (p, e['id'], digest, e['expires'], canonical(result).decode()))
            return {'duplicate': False, 'result': result, 'trust': 'untrusted-data'}

    def apply(self, d, p, e, wire, now):
        payload = e['payload']
        if not isinstance(payload, dict):
            raise ValueError('payload')
        if e['op'] == 'inbox':
            if payload:
                raise ValueError('inbox schema')
            rows = d.execute('SELECT wire FROM messages WHERE recipient=? AND acked=0 AND expires>? ORDER BY expires,id LIMIT 1', (p, now)).fetchall()
            return {'messages': [decode(r[0]) for r in rows]}
        if e['op'] == 'ack':
            if set(payload) != {'id'} or not uid(payload['id']):
                raise ValueError('ack schema')
            old = d.execute('SELECT acked FROM messages WHERE recipient=? AND id=?', (p, payload['id'])).fetchone()
            if old is None:
                raise ValueError('ack recipient')
            d.execute('UPDATE messages SET acked=1 WHERE recipient=? AND id=?', (p, payload['id']))
            return {'status': 'already-acked' if old[0] else 'acked'}
        if set(payload) != {'to', 'kind', 'parent', 'body', 'ttl', 'dedupe'}:
            raise ValueError('message schema')
        to, kind, parent, body, ttl, dedupe = (payload[k] for k in ('to', 'kind', 'parent', 'body', 'ttl', 'dedupe'))
        if not isinstance(to, str) or to not in self.roster[p]['recipients'] or kind not in ('request', 'response'):
            raise ValueError('message acl')
        # Idempotency key (rev P): optional. When present it must be a bounded
        # opaque token; two accepted messages with the same (sender, recipient,
        # dedupe) triple collapse to the first accepted message, so a client
        # retrying with the same semantic key cannot duplicate deliveries.
        if dedupe is not None and (not isinstance(dedupe, str) or not 1 <= len(dedupe) <= 64
                                   or not re.fullmatch(r'[A-Za-z0-9._:-]+', dedupe)):
            raise ValueError('dedupe key')
        if not isinstance(body, str) or not 0 < len(body.encode('utf-8')) <= MAX_BODY or type(ttl) is not int or not 1 <= ttl <= MAX_MESSAGE_TTL:
            raise ValueError('message bounds')
        if (kind == 'request' and parent is not None) or (kind == 'response' and not uid(parent)):
            raise ValueError('parent')
        # Stable expiration derives from signed issued time, never the retry's receive time.
        expires = e['issued'] + ttl
        if expires <= now:
            raise ValueError('message expired')
        if kind == 'response':
            req = d.execute('SELECT sender,recipient,kind,expires FROM messages WHERE id=?', (parent,)).fetchone()
            if not req or req[:3] != (to, p, 'request') or req[3] <= now:
                raise ValueError('response correlation')
        # Semantic dedupe (rev P): an accepted message with the same
        # (sender, recipient, dedupe) triple makes a later one a duplicate of
        # the FIRST accepted message, but ONLY while that original is still
        # live (expires>now). A retry after the original expired is a fresh
        # delivery, never a resurrection. The retry returns accepted with the
        # original id and inserts nothing.
        if dedupe is not None:
            prior = d.execute('SELECT id FROM messages WHERE sender=? AND recipient=? AND dedupe=? AND kind=? AND expires>? ORDER BY expires,id LIMIT 1',
                              (p, to, dedupe, kind, now)).fetchone()
            if prior:
                return {'status': 'accepted', 'id': prior[0], 'dedupe': 'collapsed'}
        # Separate request/response storage budgets reserve room for replies, even
        # when requests saturate a principal. No infinite retry on backpressure.
        # Acked responses no longer hold the response reservation: once consumed,
        # only unacked responses count toward the reserved slot (rev B).
        for column, principal in (('sender', p), ('recipient', to)):
            rows = self.roster[principal]['rows']
            reserved = max(1, rows // 4)
            limit = reserved if kind == 'response' else rows - reserved
            acked = ' AND acked=0' if kind == 'response' else ''
            count = d.execute('SELECT count(*) FROM messages WHERE ' + column + '=? AND kind=?' + acked,
                              (principal, kind)).fetchone()[0]
            if count >= limit:
                raise ValueError(column + ' ' + kind + ' storage quota')
        try:
            d.execute('INSERT INTO messages(id,sender,recipient,kind,parent,expires,wire,dedupe) VALUES(?,?,?,?,?,?,?,?)',
                      (e['id'], p, to, kind, parent, expires, canonical(wire).decode(), dedupe))
        except sqlite3.IntegrityError:
            raise ValueError('message id/terminal conflict')
        return {'status': 'accepted', 'id': e['id']}


class Server(HTTPServer):
    def service_actions(self):
        # Retention also runs while idle, not just when a new message succeeds.
        now = time.monotonic()
        if now >= getattr(self, '_next_prune', 0):
            self._next_prune = now + 30
            # Rev B2 review fix (F-R1, non-author review 2026-10-30): a transient
            # storage failure here (lock contention, clock-rollback hold) must not
            # kill the serve loop into a systemd StartLimit failure; RPCs re-run
            # housekeeping and still fail closed per request. The next window retries.
            try:
                self.store.prune()
            except (sqlite3.Error, OSError, ValueError) as ex:
                print('prune deferred: ' + str(ex), file=sys.stderr, flush=True)

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(3)
        return sock, addr


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        signal.setitimer(signal.ITIMER_REAL, 8)
        try:
            super().handle()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def send(self, status, obj):
        data = canonical(obj)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(405, {'error': 'signed POST only'})

    def do_POST(self):
        if self.path != '/v2/rpc':
            return self.send(404, {'error': 'not found'})
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or self.headers.get_all('Transfer-Encoding') or not re.fullmatch('[0-9]{1,5}', lengths[0]):
                raise ValueError('length')
            n = int(lengths[0])
            if not 0 < n <= MAX_WIRE:
                raise ValueError('length')
            raw = self.rfile.read(n)
            if len(raw) != n:
                raise ValueError('truncated')
            self.send(200, self.server.store.rpc(decode(raw)))
        except (ValueError, TypeError, UnicodeError, RecursionError, subprocess.TimeoutExpired):
            self.send(400, {'error': 'rejected'})
        except sqlite3.Error:
            self.send(503, {'error': 'storage unavailable'})


def deadline(*_):
    raise TimeoutError('absolute request deadline')


def require_ssh_keygen():
    # Fail fast at startup instead of rejecting every RPC with a 400/500.
    r = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', os.devnull, '-I', 'x',
                        '-n', NAMESPACE, '-s', os.devnull],
                       input=b'', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp'})
    # Any exit proves the binary exists; FileNotFoundError would have raised.
    assert r.returncode is not None


def main():
    os.umask(0o077)
    signal.signal(signal.SIGALRM, deadline)
    require_ssh_keygen()
    roster = decode(Path(os.environ['SIGNED_BOARD_ROSTER']).read_bytes())
    db_path = os.environ['SIGNED_BOARD_DB']
    if os.path.exists(db_path) and not os.path.isfile(db_path):
        raise ValueError('database path must be a regular file')
    # Fail fast on a non-SQLite file (wrong-directory refusal) instead of letting
    # the first RPC return a raw sqlite3.DatabaseError.
    try:
        store = Store(db_path, roster)
    except sqlite3.DatabaseError as ex:
        raise ValueError('database unreadable: ' + str(ex))
    port = int(os.environ.get('SIGNED_BOARD_PORT', '18792'))
    if port == 18791:
        raise ValueError('legacy pilot port forbidden')
    # Refuse held restores before binding, rather than look healthy but reject traffic.
    store.prune()
    # Production interface binding (rev P): loopback (local admin + restricted
    # sshd PermitOpen path) PLUS the tailnet address when the SIGNED_BOARD_BIND
    # file is present and carries a literal IPv4 address. A malformed file is a
    # startup error (fail closed), not a silent loopback fallback.
    hosts = ['127.0.0.1']
    bind_file = os.environ.get('SIGNED_BOARD_BIND')
    if bind_file and os.path.exists(bind_file):
        raw = Path(bind_file).read_text().strip()
        if not re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', raw):
            raise ValueError('SIGNED_BOARD_BIND must contain a literal IPv4 address')
        hosts.append(raw)
    server = None
    for host in hosts:
        try:
            server = Server((host, port), Handler)
            print('bound %s:%d' % (host, port), flush=True)
        except OSError as ex:
            if host == '127.0.0.1':
                raise
            print('tailnet bind skipped (%s): %s' % (host, ex), file=sys.stderr, flush=True)
    if server is None:
        raise ValueError('no interface bound')
    server.store = store
    server.serve_forever(poll_interval=.5)


if __name__ == '__main__':
    main()
