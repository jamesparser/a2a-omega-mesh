"""Networkless sandbox tests; disposable keys ONLY, never live device credentials.
Rev P (2026-10-31): schema v4 = lane-split quotas + semantic dedupe keys;
production board omega-mesh-prod-20261031. Legacy refusal tests cover rev A (v2)
databases; the rev B (v3) pilot DB is refused by the same version check.
"""
import base64
import concurrent.futures
import copy
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0, '/src')
import board
import recovery

ROOT = Path('/scratch')
KEYS = {}
for name in ('dummy-a', 'dummy-b', 'dummy-c'):
    key = ROOT / name
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    KEYS[name] = key
ROSTER = {n: {'key': k.with_suffix('.pub').read_text().split(' ', 2)[0] + ' ' + k.with_suffix('.pub').read_text().split(' ', 2)[1],
              'recipients': [p for p in KEYS if p != n], 'rows': 4, 'rate': 4} for n, k in KEYS.items()}


def sign(e, key=None, ns=board.NAMESPACE):
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        f = Path(tmp) / 'message'
        f.write_bytes(board.canonical(e))
        subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(key or KEYS[e['principal']]), '-n', ns, str(f)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'envelope': e, 'signature': base64.b64encode(Path(str(f) + '.sig').read_bytes()).decode()}


def env(p='dummy-a', op='post', now=None, payload=None, **kw):
    now = int(time.time()) if now is None else now
    e = {'v': 2, 'board': board.BOARD, 'principal': p, 'id': str(uuid.uuid4()),
         'issued': now, 'expires': now + 120, 'op': op,
         'payload': payload if payload is not None else {'to': 'dummy-b', 'kind': 'request', 'parent': None, 'body': 'UNTRUSTED benign fixture; never execute', 'ttl': 60, 'dedupe': None}}
    e.update(kw)
    return e


class Signed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = Path(self.tmp.name)
        self.now = 1800000000
        self.roster = copy.deepcopy(ROSTER)
        self.store = board.Store(self.path / 'db', self.roster, lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, **kwargs):
        return sign(env(now=self.now, **kwargs))

    def reject(self, w):
        with self.assertRaises((ValueError, TypeError)):
            self.store.rpc(w)

    def test_01_enforced_signatures_all_ops_and_namespace(self):
        for op in ('post', 'inbox', 'ack'):
            e = env(op=op, now=self.now)
            self.reject({'envelope': e})
            self.reject({'envelope': e, 'signature': ''})
            self.reject(sign(e, key=KEYS['dummy-b']))
            self.reject(sign(e, ns='other-namespace'))
        good = self.send()
        self.assertEqual(self.store.rpc(good)['result']['status'], 'accepted')
        bad = copy.deepcopy(good)
        bad['envelope']['payload']['body'] = 'tampered'
        self.reject(bad)
        bad = copy.deepcopy(good)
        bad['envelope']['principal'] = 'dummy-b'
        self.reject(bad)

    def test_02_freshness_audience_types_and_exact_boundary(self):
        for kw in ({'expires': self.now}, {'issued': self.now + 6}, {'issued': self.now - 121},
                   {'expires': self.now + 121}, {'issued': True}, {'expires': True},
                   {'v': True}, {'board': 'old-pilot'}, {'id': 'NOT-A-UUID'}):
            self.reject(self.send(**kw))
        self.store.rpc(self.send(issued=self.now + 5, expires=self.now + 120))

    def test_03_replay_restart_conflict_and_concurrent_commit(self):
        w = self.send()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda _: self.store.rpc(w), range(6)))
        self.assertEqual(sum(not r['duplicate'] for r in results), 1)
        self.store = board.Store(self.path / 'db', self.roster, lambda: self.now)
        self.assertTrue(self.store.rpc(w)['duplicate'])
        changed = copy.deepcopy(w['envelope'])
        changed['payload']['body'] = 'different'
        self.reject(sign(changed))
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
            self.assertEqual(d.execute('SELECT n FROM quotas').fetchone()[0], 1)

    def test_04_signed_inbox_ack_correlation_and_terminal(self):
        w = self.send()
        self.store.rpc(w)
        read = self.send(p='dummy-b', op='inbox', payload={})
        inbox = self.store.rpc(read)['result']['messages']
        self.assertEqual(inbox, [w])
        self.assertEqual(self.store.rpc(read)['result']['messages'], [w])
        self.reject(self.send(p='dummy-c', op='ack', payload={'id': w['envelope']['id']}))
        ack = self.send(p='dummy-b', op='ack', payload={'id': w['envelope']['id']})
        self.assertEqual(self.store.rpc(ack)['result']['status'], 'acked')
        self.assertTrue(self.store.rpc(ack)['duplicate'])
        response = dict(to='dummy-a', kind='response', parent=w['envelope']['id'], body='Operator fixture, not a model reply.', ttl=60, dedupe=None)
        self.store.rpc(self.send(p='dummy-b', payload=response))
        self.reject(self.send(p='dummy-b', payload=response))
        self.reject(self.send(p='dummy-c', payload=response))
        self.assertEqual(self.store.rpc(self.send(p='dummy-b', op='inbox', payload={}))['result']['messages'], [])

    def test_05_storage_reservations_and_recovery_after_retention(self):
        for _ in range(3):
            self.store.rpc(self.send())
        self.reject(self.send())
        other = {'to': 'dummy-a', 'kind': 'request', 'parent': None, 'body': 'other principal retains space', 'ttl': 60, 'dedupe': None}
        self.store.rpc(self.send(p='dummy-c', payload=other))
        old = self.send()
        self.now += 361
        self.store.prune()
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 0)
            self.assertEqual(d.execute('SELECT count(*) FROM receipts').fetchone()[0], 0)
        self.reject(old)
        self.store.rpc(self.send())

    def test_06_durable_rate_quota_and_clock_rollback(self):
        for _ in range(3):
            self.store.rpc(self.send(op='inbox', payload={}))
        self.reject(self.send(op='inbox', payload={}))
        self.store = board.Store(self.path / 'db', self.roster, lambda: self.now)
        self.reject(self.send(op='inbox', payload={}))
        self.store.rpc(self.send(p='dummy-b', op='inbox', payload={}))
        self.now += 60
        self.store.rpc(self.send(op='inbox', payload={}))
        self.now -= 1
        self.reject(self.send(op='inbox', payload={}))

    def test_07_pruned_replay_cannot_resurrect_by_clock_rollback(self):
        w = self.send()
        self.store.rpc(w)
        original = self.now
        self.now += 400
        self.store.prune()
        self.now = original
        self.reject(w)
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 0)

    def test_08_snapshot_restore_held_and_corruption_rejected(self):
        w = self.send()
        self.store.rpc(w)
        self.store.rpc(self.send(p='dummy-b', op='ack', payload={'id': w['envelope']['id']}))
        backups = self.path / 'backups'
        backups.mkdir(mode=0o700)
        snap = recovery.snapshot(self.path / 'db', backups)
        restored = recovery.restore(snap, self.path / 'restored')
        hold = board.Store(restored, self.roster, lambda: self.now)
        with self.assertRaisesRegex(ValueError, 'quarantined'):
            hold.rpc(w)
        with sqlite3.connect(restored) as d:
            self.assertEqual(d.execute('SELECT acked FROM messages').fetchone()[0], 1)
            self.assertEqual(d.execute('SELECT count(*) FROM receipts').fetchone()[0], 2)
            self.assertEqual(d.execute('SELECT sum(n) FROM quotas').fetchone()[0], 2)
        with self.assertRaises(ValueError):
            recovery.restore(snap, restored)
        raw = bytearray(snap.read_bytes())
        raw[-1] ^= 1
        snap.write_bytes(raw)
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            recovery.restore(snap, self.path / 'corrupt')

    def test_09_backup_inventory_and_schema_refuse(self):
        backups = self.path / 'backups'
        backups.mkdir(mode=0o700)
        for _ in range(4):
            recovery.snapshot(self.path / 'db', backups)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            recovery.snapshot(self.path / 'db', backups)
        with self.assertRaises(ValueError):
            recovery.snapshot(self.path / 'missing', backups)
        legacy = self.path / 'legacy'
        with sqlite3.connect(legacy) as d:
            d.execute('CREATE TABLE messages(id TEXT)')
        with self.assertRaisesRegex(ValueError, 'legacy migration'):
            board.Store(legacy, self.roster)
        changed = copy.deepcopy(self.roster)
        changed['dummy-a']['rows'] = 3
        with self.assertRaises(ValueError):
            board.Store(self.path / 'db', changed)

    def test_10_expiry_rechecked_after_crypto(self):
        w = self.send(expires=self.now + 1)
        real = self.store.verifier.verify
        def slow(*args):
            real(*args)
            self.now += 1
        self.store.verifier.verify = slow
        self.reject(w)

    def test_11_content_acl_and_parent_validation(self):
        base = env(now=self.now)['payload']
        for change in ({'body': 'x' * 8193}, {'body': ''}, {'ttl': True}, {'ttl': 3601},
                       {'to': 'dummy-a'}, {'kind': 'response', 'parent': str(uuid.uuid4())}, {'parent': str(uuid.uuid4())},
                       {'dedupe': 'bad key!'}, {'dedupe': 'x' * 65}, {'dedupe': 5}):
            self.reject(self.send(payload=dict(base, **change)))
        raw = b'{"a":1,"a":2}'
        with self.assertRaises(ValueError):
            board.decode(raw)
        with self.assertRaises(ValueError):
            board.decode(b'{"a":NaN}')


    def test_11b_semantic_dedupe_collapses_retry(self):
        # Rev P: same (sender, recipient, dedupe, kind) collapses to the first
        # accepted message; different key or different recipient does not.
        self.reject(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                       'body': 'bad key charset', 'ttl': 60, 'dedupe': 'bad key!'}))
        first = self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                   'body': 'original body', 'ttl': 600, 'dedupe': 'job-42'})
        r1 = self.store.rpc(first)['result']
        self.assertEqual(r1['status'], 'accepted')
        retry = self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                   'body': 'RETRIED body differs', 'ttl': 60, 'dedupe': 'job-42'})
        r2 = self.store.rpc(retry)['result']
        self.assertEqual(r2['status'], 'accepted')
        self.assertEqual(r2['id'], first['envelope']['id'])
        self.assertEqual(r2.get('dedupe'), 'collapsed')
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
        # different dedupe key -> separate message
        self.store.rpc(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                          'body': 'other key', 'ttl': 60, 'dedupe': 'job-43'}))
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 2)
        # dedupe=None -> no collapsing ever (new minute bucket for the data lane)
        self.now += 60
        self.store.rpc(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                          'body': 'no key', 'ttl': 60, 'dedupe': None}))
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 3)
        # same key again, new envelope/id, later minute -> still collapsed to the
        # FIRST message's id (collapsing is not bounded by the rate bucket)
        later = self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                   'body': 'much later retry', 'ttl': 60, 'dedupe': 'job-42'})
        rl = self.store.rpc(later)['result']
        self.assertEqual(rl['id'], first['envelope']['id'])
        self.assertEqual(rl.get('dedupe'), 'collapsed')
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 3)
        # dedupe is scoped per (sender, recipient): dummy-b using the same key to
        # dummy-a is a NEW message, never collapsed onto dummy-a's chain
        r3 = self.store.rpc(self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'request', 'parent': None,
                                                            'body': 'other sender same key', 'ttl': 60, 'dedupe': 'job-42'}))['result']
        self.assertNotIn('dedupe', r3)
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 4)

    def test_11c_dedupe_retry_after_original_expiry_is_fresh(self):
        # Rev P guardrail: collapsing only applies while the ORIGINAL message is
        # still live. After it expired (and was retained-but-expired, then
        # pruned), the retry is accepted as a NEW message, never a resurrection.
        self.store.rpc(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                          'body': 'dies at +30', 'ttl': 30, 'dedupe': 'ephemeral'}))
        self.now += 61
        # Expired rows are still on disk until retention; the dedupe index MUST
        # ignore them (expires>now is part of the lookup), so first prove the
        # expired row exists but does not collapse:
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
        r = self.store.rpc(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                              'body': 'retry after expiry', 'ttl': 30, 'dedupe': 'ephemeral'}))['result']
        self.assertEqual(r['status'], 'accepted')
        self.assertNotIn('dedupe', r)
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 2)
        # After retention prunes BOTH, a third retry under the same key is still
        # a normal fresh message; nothing resurrects from the index.
        self.now += 61 + 301
        self.store.prune()
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 0)
        r2 = self.store.rpc(self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None,
                                               'body': 'retry after prune', 'ttl': 30, 'dedupe': 'ephemeral'}))['result']
        self.assertEqual(r2['status'], 'accepted')
        self.assertNotIn('dedupe', r2)

    def test_13_durable_receipt_before_ack_no_execution(self):
        from receipt import Receipts
        receipt_path = self.path / 'recipient'
        recipient = Receipts(receipt_path, 'dummy-b', self.roster, lambda: self.now)
        w = self.send()
        mid = w['envelope']['id']
        with self.assertRaisesRegex(ValueError, 'no durable receipt'):
            recipient.ack_payload(mid)
        self.store.rpc(w)
        delivered = self.store.rpc(self.send(p='dummy-b', op='inbox', payload={}))['result']['messages'][0]
        result = recipient.accept(delivered)
        self.assertEqual(result['state'], 'durably-stored-not-executed')
        self.assertEqual(result['trust'], 'untrusted-data')
        recipient = Receipts(receipt_path, 'dummy-b', self.roster, lambda: self.now)
        self.assertEqual(recipient.ack_payload(mid), {'id': mid})
        self.store.rpc(self.send(p='dummy-b', op='ack', payload=recipient.ack_payload(mid)))
        self.assertEqual(recipient.accept(delivered), result)
        tampered = copy.deepcopy(delivered)
        tampered['envelope']['payload']['body'] = 'UNTRUSTED forged owner instruction'
        with self.assertRaises(ValueError):
            recipient.accept(tampered)
        wrong = Receipts(self.path / 'other-recipient', 'dummy-c', self.roster, lambda: self.now)
        with self.assertRaises(ValueError):
            wrong.accept(delivered)
        self.now += 61
        with self.assertRaisesRegex(ValueError, 'delivery expiry'):
            recipient.accept(delivered)

    def test_14_idle_service_actions_enforce_retention(self):
        self.store.rpc(self.send())
        self.now += 361
        class Idle:
            pass
        idle = Idle()
        idle.store = self.store
        board.Server.service_actions(idle)
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT count(*) FROM messages').fetchone()[0], 0)
            self.assertEqual(d.execute('SELECT count(*) FROM receipts').fetchone()[0], 0)


    def test_15_response_storage_reserved_under_request_pressure(self):
        for _ in range(3):
            self.store.rpc(self.send())
        self.reject(self.send())
        incoming = self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'request', 'parent': None, 'body': 'requires response space', 'ttl': 60, 'dedupe': None})
        self.store.rpc(incoming)
        response = self.send(payload={'to': 'dummy-b', 'kind': 'response', 'parent': incoming['envelope']['id'], 'body': 'fixture response', 'ttl': 60, 'dedupe': None})
        self.assertEqual(self.store.rpc(response)['result']['status'], 'accepted')

    def test_16_ack_response_rate_reserved_under_inbox_pressure(self):
        incoming = self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'request', 'parent': None, 'body': 'requires control quota', 'ttl': 60, 'dedupe': None})
        self.store.rpc(incoming)
        for _ in range(3):
            self.store.rpc(self.send(op='inbox', payload={}))
        self.reject(self.send(op='inbox', payload={}))
        self.store.rpc(self.send(op='ack', payload={'id': incoming['envelope']['id']}))
        response = self.send(payload={'to': 'dummy-b', 'kind': 'response', 'parent': incoming['envelope']['id'], 'body': 'fixture response', 'ttl': 60, 'dedupe': None})
        self.assertEqual(self.store.rpc(response)['result']['status'], 'accepted')
        # Control lane holds 4/min (rev B): ack, response, ack(dup), boundary ack;
        # the 5th control op is rejected.
        self.store.rpc(self.send(op='ack', payload={'id': incoming['envelope']['id']}))
        self.store.rpc(self.send(op='ack', payload={'id': incoming['envelope']['id']}))
        self.reject(self.send(op='ack', payload={'id': incoming['envelope']['id']}))


    def test_17_online_backup_sees_committed_uncheckpointed_wal(self):
        self.store.rpc(self.send())
        backups = self.path / 'backups'
        backups.mkdir(mode=0o700)
        writer = sqlite3.connect(self.path / 'db')
        try:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('UPDATE messages SET acked=1')
            writer.commit()
            self.assertGreater(Path(str(self.path / 'db') + '-wal').stat().st_size, 0)
            snap = recovery.snapshot(self.path / 'db', backups)
            with sqlite3.connect(snap) as d:
                self.assertEqual(d.execute('SELECT acked FROM messages').fetchone(), (1,))
        finally:
            writer.close()

    def test_18_sigkill_uncommitted_write_rolls_back_receipts_and_ack(self):
        w = self.send()
        self.store.rpc(w)
        code = "import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); d.execute('BEGIN IMMEDIATE'); d.execute('UPDATE messages SET acked=1'); d.execute('DELETE FROM receipts'); print('transaction-open',flush=True); time.sleep(60)"
        p = subprocess.Popen([sys.executable, '-I', '-c', code, str(self.path / 'db')], stdout=subprocess.PIPE, text=True,
                             env={'PATH': '/usr/bin:/bin', 'HOME': str(self.path), 'TMPDIR': str(self.path)})
        try:
            self.assertEqual(p.stdout.readline().strip(), 'transaction-open')
        finally:
            p.kill()
            p.wait(5)
            p.stdout.close()
        self.store = board.Store(self.path / 'db', self.roster, lambda: self.now)
        self.assertTrue(self.store.rpc(w)['duplicate'])
        with self.store.db() as d:
            self.assertEqual(d.execute('SELECT acked FROM messages').fetchone(), (0,))
            self.assertEqual(d.execute('SELECT count(*) FROM receipts').fetchone(), (1,))


class RevB(unittest.TestCase):
    """Non-author review fixes (2026-10-30): F1 lane quotas, F2 acked-exempt
    response reservation, F5 startup hardening, F6 min rate, F7 redaction."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = Path(self.tmp.name)
        self.now = 1800000000
        self.roster = copy.deepcopy(ROSTER)
        self.store = board.Store(self.path / 'db', self.roster, lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, **kwargs):
        return sign(env(now=self.now, **kwargs))

    def reject(self, w):
        with self.assertRaises((ValueError, TypeError)):
            self.store.rpc(w)

    def test_19_lanesplit_quota_keeps_control_headroom_under_data_pressure(self):
        # F1 regression: data ops (inbox polls) saturate the data lane; ack and
        # response must still succeed because control has its own lane.
        for _ in range(3):
            self.store.rpc(self.send(op='inbox', payload={}))
        self.reject(self.send(op='inbox', payload={}))
        incoming = self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'request', 'parent': None, 'body': 'lane headroom', 'ttl': 60, 'dedupe': None})
        self.store.rpc(incoming)
        ack = self.send(op='ack', payload={'id': incoming['envelope']['id']})
        self.assertEqual(self.store.rpc(ack)['result']['status'], 'acked')
        response = self.send(payload={'to': 'dummy-b', 'kind': 'response', 'parent': incoming['envelope']['id'], 'body': 'lane headroom reply', 'ttl': 60, 'dedupe': None})
        self.assertEqual(self.store.rpc(response)['result']['status'], 'accepted')
        self.reject(self.send(op='inbox', payload={}))
        with self.store.db() as d:
            lanes = dict(d.execute("SELECT lane,n FROM quotas WHERE principal='dummy-a' AND bucket=?", (self.now // 60,)).fetchall())
        self.assertEqual(lanes, {'data': 3, 'control': 2})

    def test_20_acked_response_frees_reservation_no_self_squat(self):
        # F2 regression: a consumed (acked) response no longer blocks the next one.
        incoming = self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None, 'body': 'needs reply', 'ttl': 600, 'dedupe': None})
        self.store.rpc(incoming)
        first = self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'response', 'parent': incoming['envelope']['id'], 'body': 'first reply', 'ttl': 600, 'dedupe': None})
        self.store.rpc(first)
        # Recipient acks the consumed response; the freed slot must be reusable.
        self.store.rpc(self.send(op='ack', payload={'id': first['envelope']['id']}))
        request2 = self.send(payload={'to': 'dummy-b', 'kind': 'request', 'parent': None, 'body': 'needs reply 2', 'ttl': 600, 'dedupe': None})
        self.store.rpc(request2)
        second = self.send(p='dummy-b', payload={'to': 'dummy-a', 'kind': 'response', 'parent': request2['envelope']['id'], 'body': 'second reply', 'ttl': 600, 'dedupe': None})
        self.assertEqual(self.store.rpc(second)['result']['status'], 'accepted')

    def test_21_acked_response_still_counts_for_plain_request_rows(self):
        # Guardrail: only the response reservation is acked-exempt; request-side
        # counting is unchanged so total capacity stays bounded.
        for _ in range(3):
            w = self.send()
            self.store.rpc(w)
            self.store.rpc(self.send(p='dummy-b', op='ack', payload={'id': w['envelope']['id']}))
        self.reject(self.send())

    def test_22_revA_revB_schema_and_non_sqlite_refused(self):
        # F5 + rev P: BOTH legacy schemas (rev A user_version=2, rev B v3) must
        # be refused, and a non-SQLite file raises ValueError
        # ('unreadable'/'wrong database'), not a raw sqlite3.DatabaseError.
        legacy = self.path / 'legacy.db'
        with sqlite3.connect(legacy) as d:
            d.executescript("PRAGMA application_id=%d; PRAGMA user_version=2; CREATE TABLE messages(id TEXT);" % board.APP_ID)
        with self.assertRaisesRegex(ValueError, 'wrong database'):
            board.Store(legacy, self.roster)
        revb = self.path / 'revb.db'
        with sqlite3.connect(revb) as d:
            d.executescript("PRAGMA application_id=%d; PRAGMA user_version=3; CREATE TABLE messages(id TEXT);" % board.APP_ID)
        with self.assertRaisesRegex(ValueError, 'wrong database'):
            board.Store(revb, self.roster)
        junk = self.path / 'junk.db'
        junk.write_bytes(b'this is not a sqlite database at all........')
        with self.assertRaises(ValueError):
            board.Store(junk, self.roster)

    def test_23_minimum_rate_enforced_in_roster_validation(self):
        # F6: rate below 4 refuses (data lane would keep < 3 ops/minute).
        bad = copy.deepcopy(self.roster)
        bad['dummy-a']['rate'] = 2
        with self.assertRaises(ValueError):
            board.Store(self.path / 'db2', bad)
        ok = copy.deepcopy(self.roster)
        ok['dummy-a']['rate'] = 4
        board.Store(self.path / 'db3', ok)

    def test_24_log_redact_masks_token_shaped_values(self):
        # F7: the redaction helper must actually mask long opaque strings.
        from log_redact import log_redact
        secret = 'A' * 40
        out = log_redact({'a': [secret, 'short'], 'b': 'plain sentence with spaces', 'c': 5})
        self.assertNotIn(secret, str(out))
        self.assertIn('short', str(out))
        self.assertIn('plain sentence with spaces', str(out))
        self.assertEqual(out['c'], 5)
        twice = log_redact(log_redact(secret))
        self.assertEqual(log_redact(secret), twice)


    def test_25_idle_prune_transient_failure_survives(self):
        # F-R1 regression (revB2, non-author review): a transient prune failure
        # (storage error / rollback hold) during service_actions must NOT kill
        # the server; retention retries next window and RPCs stay functional.
        w = self.send()
        self.store.rpc(w)
        class Idle:
            pass
        idle = Idle()
        real = self.store.prune
        calls = []
        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError('database is locked')
            return real()
        idle.store = self.store
        self.store.prune = flaky
        board.Server.service_actions(idle)  # must not raise
        self.store.prune = real
        self.assertEqual(self.store.rpc(self.send(p='dummy-b', op='inbox', payload={}))['result']['messages'], [w])

    def test_26_rollback_hold_prune_is_not_fatal_when_idle(self):
        # F-R1 regression: a clock-rollback hold during idle prune must not kill
        # the server either; the hold still applies to RPC paths (fail closed).
        self.store.rpc(self.send())
        class Idle:
            pass
        idle = Idle()
        idle.store = self.store
        real_clock = self.store.clock
        self.store.clock = lambda: self.now - 10
        board.Server.service_actions(idle)  # ValueError('clock rollback hold') swallowed
        self.store.clock = real_clock
        # The hold is permissive again once the clock catches up; the server must
        # have survived and keep serving (fail-closed applies per RPC, not idle).
        w = self.send()
        self.assertEqual(self.store.rpc(w)['result']['status'], 'accepted')


class HTTP(unittest.TestCase):
    def test_12_http_crash_restart_no_unsigned_or_legacy_routes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as root:
            root = Path(root)
            (root / 'roster').write_bytes(board.canonical(ROSTER))
            cfg = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'TMPDIR': str(root),
                   'SIGNED_BOARD_DB': str(root / 'db'), 'SIGNED_BOARD_ROSTER': str(root / 'roster'),
                   'SIGNED_BOARD_PORT': '18792'}
            def start():
                p = subprocess.Popen([sys.executable, '-I', '/src/board.py'], env=cfg)
                for _ in range(100):
                    if p.poll() is not None:
                        raise RuntimeError('server exited')
                    try:
                        with socket.create_connection(('127.0.0.1', 18792), .1):
                            return p
                    except OSError:
                        time.sleep(.05)
                p.kill()
                raise RuntimeError('startup timeout')
            def call(obj, path='/v2/rpc', method='POST', raw=None):
                c = http.client.HTTPConnection('127.0.0.1', 18792, timeout=4)
                c.request(method, path, body=raw if raw is not None else board.canonical(obj))
                r = c.getresponse()
                answer = (r.status, json.loads(r.read()))
                c.close()
                return answer
            p = start()
            try:
                w = sign(env())
                self.assertEqual(call(w)[0], 200)
                self.assertEqual(call({'envelope': w['envelope']})[0], 400)
                self.assertEqual(call(w, '/v1/messages')[0], 404)
                self.assertEqual(call(w, method='GET')[0], 405)
                self.assertEqual(call(None, raw=b'x' * (board.MAX_WIRE + 1))[0], 400)
                self.assertEqual(call(None, raw=b'{"x":1,"x":2}')[0], 400)
                p.kill()
                p.wait(5)
                p = start()
                self.assertTrue(call(w)[1]['duplicate'])
                self.assertEqual(call(sign(env(p='dummy-b', op='inbox', payload={})))[1]['result']['messages'], [w])
            finally:
                p.kill()
                p.wait(5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
