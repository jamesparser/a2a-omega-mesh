"""Build the PRODUCTION roster on Omega (2026-10-31).

Fleet-wide enrollment: rci-vps (Omega) is the hub; every other principal can
post only to rci-vps (hub-and-spoke; a device reaches another device by asking
the hub to relay, which keeps the ACL simple and auditable). Keys are each
device's OWN key, generated on-box where new (s21fe, exodus), existing
credentialed keys elsewhere; pubkeys were distributed over the existing SSH
channels and only the PUBLIC halves are embedded here. No secrets printed.

Refuses to overwrite an existing roster with different content (same rule as
the revB2 builder).
"""
import hashlib
import json
import pathlib
import subprocess
import sys

ROSTER_PATH = pathlib.Path('/opt/mesh-board-prod-20261031/roster.json')

# Public halves only. rci-vps/googlevps/s24: pre-existing keys (no rotation).
# laptop: mesh-laptop (already authorized on omega root ssh).
# s21fe + exodus: generated ON each device 2026-10-31, pulled over pinned SSH.
PUBS = {
    'rci-vps': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEZ+Asv5+4KcQ3ZEqn5T/uncn9zrlWf91LG/DfTyHEHA',
    'googlevps': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKAaDfBrVwH9aYe2ODxOje7dChoDKptrjfAqiMKh/ojt',
    's24': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHyP2+j9GbQiF8pl/USJaOmLUzgEfwcxk7HyE+M4By+s',
    'laptop': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNebuc+Xs/kbfRzCri+O5gV8M36IEBQ3r1o5RFMoQoz',
    's21fe': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBSfklBMqSxy+aRqPOWQvlwe8GlRKq1c0VlPdv9V8XPy',
    'exodus': 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPGWyKm1d2wyJ0pfSbvtAbBEW3oj7gNxNO7eu6Zdd+Xx',
}

DEVICES = ('googlevps', 's24', 'laptop', 's21fe', 'exodus')

roster = {
    'rci-vps': {
        'key': PUBS['rci-vps'],
        'recipients': list(DEVICES),   # hub can post to every device
        'rows': 16,
        'rate': 8,
    },
}
for name in DEVICES:
    roster[name] = {
        'key': PUBS[name],
        'recipients': ['rci-vps'],     # spokes post to the hub only
        'rows': 8,
        'rate': 8,
    }

canon = json.dumps(roster, sort_keys=True, separators=(',', ':')).encode()
ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
if ROSTER_PATH.exists():
    existing = ROSTER_PATH.read_bytes()
    if existing != canon:
        sys.exit('roster already exists with different content; refusing overwrite')
else:
    ROSTER_PATH.write_bytes(canon)
ROSTER_PATH.chmod(0o644)

print('sha256', hashlib.sha256(canon).hexdigest())
for name, peer in roster.items():
    fp = subprocess.run(['ssh-keygen', '-lf', '/dev/stdin'], input=peer['key'] + '\n',
                        capture_output=True, text=True)
    print(name, fp.stdout.strip())
