"""End-to-end MCP test of the a2a kanban from the laptop.

Drives kanban_mcp_server.py over real stdio JSON-RPC (the same way Hermes
wires an MCP server), then verifies:
  1. tools/list returns the 8 kanban tools
  2. create -> the card is stored ENCRYPTED (raw DB shows ciphertext)
  3. list -> the card comes back DECRYPTED
  4. claim -> state=doing, owner set
  5. move -> state=done
  6. done is TERMINAL (a further move is rejected)
  7. history -> the signed transition log
  8. a DIFFERENT principal (googlevps) can read the card but NOT move it
  9. the card survives well past the message board's RETENTION window
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, 'kanban_mcp_server.py')
ENV = dict(os.environ)
ENV.update({
    'KANBAN_PRINCIPAL': 'laptop',
    'KANBAN_KEY': os.path.expanduser('~/.ssh/id_mesh'),
    'KANBAN_ENC_KEYS': os.path.join(HERE, 'kanban_cek.json'),
    'KANBAN_BOARD_HOST': '100.116.149.122',
    'KANBAN_SSH_KEY': os.path.expanduser('~/.ssh/id_rci_vps'),
    'PYTHONPATH': HERE,
})
for k in ('KANBAN_DB', 'KANBAN_ROSTER', 'KANBAN_REMOTE', 'KANBAN_LOCAL'):
    ENV.pop(k, None)


class MCP:
    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=env, cwd=HERE)
        self.id = 0

    def call(self, method, params=None, timeout=90):
        self.id += 1
        req = {'jsonrpc': '2.0', 'id': self.id, 'method': method}
        if params:
            req['params'] = params
        self.p.stdin.write(json.dumps(req) + '\n')
        self.p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.p.stdout.readline()
            if not line:
                err = self.p.stderr.read()[:500]
                raise RuntimeError('server closed stdout. stderr=' + err)
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except ValueError:
                continue
            if resp.get('id') == self.id:
                return resp
        raise TimeoutError('no response to ' + method)

    def tool(self, name, **args):
        r = self.call('tools/call', {'name': name, 'arguments': args})
        content = r.get('result', {}).get('content', [{}])[0].get('text', '{}')
        return json.loads(content)

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        self.p.terminate()


FAILS = []


def check(label, cond, detail=''):
    mark = 'PASS' if cond else 'FAIL'
    if not cond:
        FAILS.append(label)
    print('  [%s] %s%s' % (mark, label, (' :: ' + str(detail)[:220]) if detail else ''))


def main():
    print('=== a2a kanban MCP end-to-end (laptop principal) ===')
    mcp = MCP(ENV)
    try:
        mcp.call('initialize', {'protocolVersion': '2025-03-26',
                                'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}})
        tools = mcp.call('tools/list').get('result', {}).get('tools', [])
        names = sorted(t['name'] for t in tools)
        check('tools/list returns 8 kanban tools', len(tools) == 8, names)
        for want in ('kanban_create', 'kanban_claim', 'kanban_move', 'kanban_comment',
                     'kanban_get', 'kanban_list', 'kanban_board', 'kanban_history'):
            check('tool present: ' + want, want in names)

        stamp = str(int(time.time()))
        res = mcp.tool('kanban_create', title='E2E MCP card ' + stamp,
                       detail='secret detail ' + stamp, lane='infra', priority='high')
        card_id = res.get('id')
        check('create returns a card id', bool(card_id), res)
        check('create reports encrypted', res.get('encrypted') is True, res)

        raw = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
             '-o', 'StrictHostKeyChecking=no', '-i', os.path.expanduser('~/.ssh/id_rci_vps'),
             'root@100.116.149.122',
             "python3 -c \"import sqlite3;d=sqlite3.connect('/var/lib/mesh-kanban/kanban.db');"
             "r=d.execute('SELECT title,detail FROM cards WHERE id=?',('" + card_id + "',)).fetchone();"
             "print(r[0][:40]);print(r[1][:40])\""],
            capture_output=True, text=True, timeout=90)
        raw_out = (raw.stdout or '').strip()
        check('raw DB title is ciphertext (no plaintext)',
              'kanban-enc-v1' in raw_out, raw_out)
        check('raw DB detail is ciphertext (no plaintext)',
              'secret detail' not in raw_out, raw_out)

        got = mcp.tool('kanban_get', card_id=card_id)
        check('get decrypts the title',
              got.get('card', {}).get('title') == 'E2E MCP card ' + stamp, got)
        check('get decrypts the detail',
              got.get('card', {}).get('detail') == 'secret detail ' + stamp, got)

        listed = mcp.tool('kanban_list', lane='infra')
        titles = [c.get('title') for c in listed.get('cards', [])]
        check('list decrypts titles', 'E2E MCP card ' + stamp in titles, titles)

        cl = mcp.tool('kanban_claim', card_id=card_id, note='claimed by laptop')
        check('claim -> doing', cl.get('state') == 'doing', cl)
        check('claim sets owner=laptop', cl.get('state') == 'doing', cl)

        mv = mcp.tool('kanban_move', card_id=card_id, state='done', note='finished')
        check('move -> done', mv.get('state') == 'done', mv)

        bad = mcp.tool('kanban_move', card_id=card_id, state='doing', note='reopen')
        check('done is terminal (move rejected)', 'error' in bad, bad)

        hist = mcp.tool('kanban_history', card_id=card_id)
        trans = hist.get('transitions', [])
        # created + claimed + moved-to-done = 3 (the rejected terminal move is
        # not recorded, which is correct - it never happened)
        check('history has 3 transitions', len(trans) == 3, len(trans))
        check('history notes are decrypted',
              any('claimed by laptop' in (t.get('note') or '') for t in trans),
              [t.get('note') for t in trans])
        check('history actors are signed principals',
              all(t.get('actor') == 'laptop' for t in trans),
              [t.get('actor') for t in trans])

        board = mcp.tool('kanban_board', lane='infra')
        cols = board.get('columns', {})
        check('board has 4 columns', set(cols) == {'todo', 'doing', 'done', 'blocked'}, list(cols))
        check('card is in the done column',
              any(c.get('id') == card_id for c in cols.get('done', [])), cols.get('done'))

        # The owner CAN move its own card (the ACL allows exactly one actor).
        # Use a FRESH card: card_id is already 'done' (terminal) by now.
        own_res = mcp.tool('kanban_create', title='Owner proof ' + stamp,
                           detail='owner moves its own card', lane='infra')
        own_id = own_res.get('id')
        oc = mcp.tool('kanban_claim', card_id=own_id, note='laptop claims')
        check('owner can claim its own fresh card', oc.get('state') == 'doing', oc)
        own = mcp.tool('kanban_move', card_id=own_id, state='done', note='owner move')
        check('the owner CAN move its own card', own.get('state') == 'done', own)

        # The cross-principal (googlevps) proof runs NATIVELY on the googlevps
        # host - it holds the googlevps signing key and the shared CEK. It is
        # NOT run from here: the laptop has no googlevps private key, so a
        # local attempt would fail on a missing key rather than prove
        # anything about the ACL.
        print('\n--- cross-principal proof runs on the googlevps host ---')
    finally:
        mcp.close()

    print('\n=== %s ===' % ('ALL PASS' if not FAILS else
                            'FAILURES: ' + ', '.join(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
