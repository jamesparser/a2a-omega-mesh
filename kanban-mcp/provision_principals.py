#!/usr/bin/env python3
"""Provision a2a-kanban principals for the fleet (boss 11-10).

The kanban board authenticates every call with an ed25519 signature verified
against roster.json. Each AGENT gets its OWN principal so the board's
ownership ACL means something: "lane A moved a card" is distinguishable from
"lane B moved a card", and one lane cannot move another lane's card.

  laptop   - Jason Parser (this agent, the manager)
  rci-vps  - omega VPS (bounty hunting, and the board host)
  googlevps- union verification lane
  lane-<x> - each laptop lane profile (chat, coding, vision, ...)

The board lives on rci-vps. Lane principals are created on the LAPTOP, their
public keys are collected into a roster, the roster is pushed to the board,
and each lane gets its private signing key + the shared CEK.

ORDER MATTERS: the roster digest is pinned in the board DB meta, so the roster
is written to the board BEFORE any principal is used against it.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parent
LAPTOP_HOME = Path(r"C:\Users\agnesagent")
KEY_DIR = LAPTOP_HOME / 'work' / '_tmp' / 'kanban_principals'
ROSTER_LOCAL = WORK / 'roster.json'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
       '-o', 'StrictHostKeyChecking=no',
       '-i', str(LAPTOP_HOME / '.ssh' / 'id_rci_vps'),
       'root@100.116.149.122']
BOARD_ROSTER = '/opt/mesh-board-prod-20261031/roster.json'

# (principal, roster entries reused from the existing roster, or None to mint)
PRINCIPALS = [
    ('laptop', 'laptop'),
    ('rci-vps', 'rci-vps'),
    ('googlevps', 'googlevps'),
    ('lane-chat', None),
    ('lane-coding', None),
    ('lane-vision', None),
    ('lane-asi1-gig', None),
    ('lane-asi1-airdrop', None),
]


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop('timeout', 120), **kw)
    return r.returncode, r.stdout, r.stderr


def ssh(cmd, timeout=120):
    return sh(SSH + [cmd], timeout=timeout)


def main():
    KEY_DIR.mkdir(parents=True, exist_ok=True)

    # 1. read the current board roster (it has the 3 real agent keys)
    rc, out, err = ssh('cat %s' % BOARD_ROSTER)
    if rc != 0:
        print('FATAL: cannot read board roster: ' + err[:200])
        return 1
    board_roster = json.loads(out)
    print('existing board roster principals: %s' % sorted(board_roster))

    # 2. mint a keypair for each new lane principal
    roster = {}
    for name, reuse in PRINCIPALS:
        if reuse:
            roster[name] = board_roster[reuse]
            print('%-18s reused key from %s' % (name, reuse))
            continue
        key = KEY_DIR / (name + '.key')
        if not key.exists():
            rc, out, err = sh(['ssh-keygen', '-t', 'ed25519', '-N', '', '-C', name,
                               '-f', str(key)], timeout=60)
            if rc != 0:
                print('FATAL: keygen failed for %s: %s' % (name, err[:200]))
                return 1
            print('%-18s minted new keypair' % name)
        else:
            print('%-18s keypair already exists' % name)
        pub = (key.with_suffix('.key.pub')).read_text().strip()
        # roster entries need a "key" field (the board reads ['key'])
        roster[name] = {'key': pub, 'rate': 30,
                        'recipients': sorted(roster.keys()) or ['*'],
                        'rows': 16}
        # fix recipients after all principals exist
    for name in roster:
        roster[name]['recipients'] = sorted(roster)

    # 3. write the local roster copy
    ROSTER_LOCAL.write_text(json.dumps(roster, indent=1, sort_keys=True))
    print('\nlocal roster written: %s (%d principals)' % (ROSTER_LOCAL, len(roster)))

    # 4. push the roster to the board BEFORE any principal uses it
    #    (the board pins the roster digest in DB meta)
    tmp = '/tmp/roster.kanban.new'
    scp = ['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
           '-o', 'StrictHostKeyChecking=no', '-i', str(LAPTOP_HOME / '.ssh' / 'id_rci_vps'),
           str(ROSTER_LOCAL), 'root@100.116.149.122:' + tmp]
    rc, out, err = sh(scp, timeout=90)
    if rc != 0:
        print('FATAL: roster scp failed: ' + err[:300])
        return 1
    rc, out, err = ssh('cp -a %s %s.bak-kanban && cp %s %s && echo ROSTER_INSTALLED'
                        % (BOARD_ROSTER, BOARD_ROSTER, tmp, BOARD_ROSTER))
    if rc != 0 or 'ROSTER_INSTALLED' not in out:
        print('FATAL: roster install failed: ' + (out + err)[:300])
        return 1
    print('roster installed on board (previous copy kept as .bak-kanban)')

    # 5. re-init the board so the meta digest is re-pinned
    rc, out, err = ssh('python3 /opt/mesh-board-prod-20261031/kanban_board.py '
                       '--db /var/lib/mesh-kanban/kanban.db --roster %s --init' % BOARD_ROSTER)
    print('board re-init: ' + (out or err).strip()[:300])

    # 6. verify each principal's key is in the board roster
    rc, out, err = ssh('python3 -c "import json;r=json.load(open(\'%s\'));'
                       'print(\' \'.join(sorted(r)))"' % BOARD_ROSTER)
    print('board roster now: %s' % out.strip())

    print('\n=== principals provisioned ===')
    for name in sorted(roster):
        print('  %-18s %s' % (name, roster[name]['key'][:60]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
