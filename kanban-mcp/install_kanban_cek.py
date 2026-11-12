#!/usr/bin/env python3
"""Write the shared kanban CEK to a local key file, reading it from STDIN.

Usage: echo '<base64 cek>' | python3 install_kanban_cek.py <path>

The CEK never appears in argv (argv is visible in process listings) and is
never echoed to stdout.
"""
import base64
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
board = sys.argv[2] if len(sys.argv) > 2 else 'omega-kanban-20261110'

raw = sys.stdin.read().strip()
if raw.startswith('CEK '):
    raw = raw[4:].strip()
cek = base64.b64decode(raw, validate=True)
if len(cek) != 32:
    print('bad CEK length', file=sys.stderr)
    sys.exit(1)

data = {'board': board, 'cek': base64.b64encode(cek).decode()}
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix('.tmp')
tmp.write_text(json.dumps(data, sort_keys=True, indent=1))
try:
    os.chmod(tmp, 0o600)
except OSError:
    pass
tmp.replace(path)
try:
    os.chmod(path, 0o600)
except OSError:
    pass
print('WROTE ' + str(path) + ' sha256=' +
      __import__('hashlib').sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16])
