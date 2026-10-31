"""Trusted operator runner for rev B: upload candidate only; run no-network disposable sandbox.
No services, actors, credentials, global SSH policy, legacy DB or spools changed.
Profile mirrors run_sandbox.py from mesh_signed_candidate_20261030 (18/18 OK), plus log_redact.py.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

LOCAL = Path(__file__).resolve().parent
REMOTE = '/root/mesh-v2-revb2-20261030'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'HostKeyAlias=100.116.149.122', 'vps-battlechan-public']
files = ['board.py', 'recovery.py', 'receipt.py', 'log_redact.py', 'test_signed.py']
for name in files:
    code = 'import pathlib,sys,hashlib; p=pathlib.Path(' + repr(REMOTE) + '); p.mkdir(mode=0o755,exist_ok=True); p.chmod(0o755); f=p/' + repr(name) + '; f.write_bytes(sys.stdin.buffer.read()); f.chmod(0o644); print(hashlib.sha256(f.read_bytes()).hexdigest())'
    raw = (LOCAL / name).read_bytes()
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(code)], input=raw, capture_output=True, check=True, timeout=30)
    if result.stdout.decode().strip() != hashlib.sha256(raw).hexdigest():
        raise RuntimeError('remote source readback mismatch for ' + name)
cmd = ['timeout', '150', 'docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '65534:65534',
       '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '48', '--memory', '192m',
       '--cpus', '1', '--ulimit', 'nofile=128:128', '--ulimit', 'fsize=67108864:67108864',
       '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=96m,mode=0700,uid=65534,gid=65534',
       '--mount', 'type=bind,src=' + REMOTE + ',dst=/src,readonly',
       '--mount', 'type=bind,src=/usr,dst=/usr,readonly',
       '--mount', 'type=bind,src=/lib,dst=/lib,readonly',
       '--mount', 'type=bind,src=/lib64,dst=/lib64,readonly',
       '--workdir', '/scratch', '--entrypoint', '/usr/bin/env', '2bf10b939b82',
       '-i', 'PATH=/usr/bin:/bin', 'HOME=/scratch', 'TMPDIR=/scratch', 'PYTHONDONTWRITEBYTECODE=1',
       '/usr/bin/python3', '-I', '/src/test_signed.py']
r = subprocess.run(SSH + [shlex.join(cmd)], capture_output=True, text=True, timeout=200)
report = {'returncode': r.returncode, 'command': shlex.join(cmd),
          'source_sha256': {n: hashlib.sha256((LOCAL / n).read_bytes()).hexdigest() for n in files},
          'stdout': r.stdout, 'stderr': r.stderr}
(LOCAL / ('revb_sandbox_evidence_' + str(time.time_ns()) + '.json')).write_text(json.dumps(report, indent=2))
(LOCAL / 'revb_sandbox_evidence.json').write_text(json.dumps(report, indent=2))
print(r.stdout, end='')
print(r.stderr, end='')
print('REVB_SANDBOX_EXIT', r.returncode)
sys.exit(r.returncode)
