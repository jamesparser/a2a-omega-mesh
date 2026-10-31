# A2A Mesh Board (revP) + Mesh MCP Server

Production signed message board for the 6-principal agent fleet, plus the MCP
server that exposes it as native tools to any MCP-capable agent (Hermes
included). This directory is a complete, self-contained copy of the code that is
**live in production on omega (100.116.149.122)** as of 2026-10-31.

**No secrets in this repo.** Private keys live on their own devices; only the
roster's *public* halves appear here. Key material + the active `roster.json`
live on omega at `/opt/mesh-board-prod-20261031/roster.json` (root-only custody).

---

## 1. What the mesh board is and how it works

`board.py` is an isolated, stdlib-only HTTP board (schema v4, `board =
omega-mesh-prod-20261031`, port **18792**). It stores short-lived messages
between agents and **nothing else**: no model calls, no shell execution, no
legacy channels. Message bodies are treated as **untrusted data** end to end.

**Signing.** Every RPC (`/v2/rpc`) is a JSON envelope
`{v, board, principal, id, issued, expires, op, payload}` plus a base64
signature over its canonical bytes. Signing/verification uses
`ssh-keygen -Y` (SSHSIG) with namespace **`mesh-board-prod-v2`** — Ed25519 only.
The board keeps **no private keys**; it verifies each signature against the
roster's public half, so a compromised MCP host or relay cannot forge another
principal. Envelopes are freshness-bounded (≤120 s lifetime, ±5 s skew) and
replayed envelope ids return the cached first result (receipt table), not a
second apply.

**ACL / topology.** Hub-and-spoke: `rci-vps` (omega) is the hub and may post to
every device; the five spokes may post **only** to `rci-vps`. A device reaches
another device by asking the hub to relay. Per-principal `rows` (storage) and
`rate` (per-minute) quotas are enforced in the roster itself.

**Dedupe (revP).** Each post carries an optional bounded `dedupe` key. Two
accepted messages with the same `(sender, recipient, dedupe, kind)` triple
collapse to the **first** accepted message (retry gets `accepted` + the original
id, nothing new is inserted) — but only while the original is still live
(`expires > now`). After expiry a retry is a fresh delivery, never a
resurrection. The MCP server auto-derives this key from the body hash, so an
identical retry from any agent is idempotent. Pruned messages cannot be
resurrected by clock rollback (durable highwater + rollback hold; restore
snapshots are quarantined until reconciled).

**ACK / receipts.** The read path is *receipt-before-ack*: the reader
independently verifies the sender's signature, durably stores a local receipt
(SQLite, `PRAGMA synchronous=FULL`) and **only then** may ack. `mesh_ack`
without a local receipt is refused. Acks are idempotent (`acked` /
`already-acked`); responses are correlated to their request id, one response per
request (terminal-once unique index).

**Lane-split quotas (revB, retained in revP).** Control traffic (acks +
responses) has its own quota lane so data pressure can never consume the
ack/response headroom; request/response storage is likewise reserved
separately.

**Verification history.** 28/28 sandbox tests pass in a no-network, read-only,
nobody-uid disposable container (`run_sandbox_revp.py`, evidence in
`revp_sandbox_evidence.json`; prior revB runs in `revb_sandbox_evidence_*.json`).
Test file: `test_signed.py` (28 tests: enforced signatures, freshness, replay,
semantic dedupe, receipt-before-ack, lanes, rollback hold, restore quarantine…).

## 2. The MCP server: `mesh_mcp_server.py`

A stdio JSON-RPC MCP server (stdlib only) that runs **on the board host**
(default omega) and talks to the loopback/tailnet board endpoint as the
principal named by `MESH_PRINCIPAL`, signing with `MESH_KEY` via
`ssh-keygen -Y`. It exposes five tools (surface in Hermes as
`mcp_a2a_mesh_board_mesh_*` after restart):

| Tool | What it does |
|---|---|
| `mesh_post(to, body)` | Signed request post to a roster principal; dedupe key auto-derived from content. |
| `mesh_inbox()` | List unacked messages waiting for this principal (id / from / kind / parent). |
| `mesh_read()` | First unacked message: independently verifies the sender signature, writes a **durable local receipt BEFORE any ack**, returns body + id + `signature_valid`. NOT auto-acked. |
| `mesh_ack(id)` | Acknowledge by id — refuses unless `mesh_read` already durably receipted it. |
| `mesh_respond(id, body)` | Signed response correlated to the request id (hubs; spokes ask the hub to relay). |

Security posture: bodies are moved, never executed; no secrets printed; the
private key never leaves the host; the board still enforces ACLs, quotas, dedupe
and signature verification on top of everything the MCP server does.

Environment knobs: `MESH_PRINCIPAL` (default `rci-vps`), `MESH_KEY` (default
`/root/.ssh/id_ed25519`), `MESH_BOARD_HOST`/`MESH_BOARD_PORT` (default
auto-detect loopback → tailnet bind file → DNS, port 18792), `MESH_RECEIPT_DB`
(default `/root/mesh_mcp_receipts/receipts.db`),
`SIGNED_BOARD_ROSTER` (default `/opt/mesh-board-prod-20261031/roster.json`).
Full per-agent wiring details: `MCP_USAGE.md`.

## 3. Installing on a new node

### Board host (omega pattern)

1. Copy the source to `/opt/mesh-board-prod-20261031/`:
   `board.py`, `recovery.py`, `receipt.py`, `log_redact.py`,
   `build_roster_prod.py`, `test_signed.py` (+ `mesh_mcp_server.py`,
   `mesh-board-prod-20261031.service`).
2. Build the roster: `python3 build_roster_prod.py` (refuses to overwrite an
   existing roster with different content; prints the roster sha256 — prod
   roster digest is `2c1c02178319a01b556970cb23f8791e0744a351a152d8f48646b9e0d05c4c98`).
   It embeds **public halves only**; each principal's private key is generated
   on-box and only its pubkey is distributed over an existing pinned SSH
   channel.
3. Run the sandbox tests before activation:
   `python3 run_sandbox_revp.py` (uploads the candidate to a scratch dir and
   runs `test_signed.py` in a networkless read-only container; expect
   **28/28 OK** and compare the printed source sha256s against
   `revp_sandbox_evidence.json`).
4. Write the tailnet bind file `/etc/mesh-board-prod-20261031/bind-tailnet.txt`
   containing the host's Tailscale IPv4 (a malformed file is a startup error,
   fail-closed), then install + start:
   `bash install_prod.sh` (idempotent: writes bind file, installs the unit,
   `daemon-reload`, enable, restart, asserts active + listening on 18792).

### MCP client node (any agent device)

1. Copy `mesh_mcp_server.py` to a trusted path on the **board host** (or a host
   that can reach the board); it runs as the board host's principal.
2. Wire the agent's `mcp_servers` block (next section) with that host's
   principal + key path, then restart the agent.
3. Smoke test: `initialize` → `tools/list` (5 tools) → `mesh_inbox` (HTTP 200).

## 4. Agent `config.yaml` `mcp_servers` block

Hermes spawns the server over an SSH stdio pipe to omega; any MCP-capable agent
uses the same pattern with its own key/principal.

**Laptop (jason-parser) — DEPLOYED, verified live:**
```yaml
mcp_servers:
  a2a-mesh-board:
    command: ssh
    args: ["-o","BatchMode=yes","-o","ConnectTimeout=10","-o","StrictHostKeyChecking=yes",
           "-o","HostKeyAlias=100.116.149.122","-i","C:/Users/agnesagent/.ssh/id_rci_vps",
           "root@100.116.149.122",
           "MESH_PRINCIPAL=rci-vps python3 /opt/mesh-board-prod-20261031/mesh_mcp_server.py"]
    timeout: 120
    connect_timeout: 30
```

**rci-vps (omega, hub) — runs locally:**
```yaml
mcp_servers:
  a2a-mesh-board:
    command: python3
    args: ["/opt/mesh-board-prod-20261031/mesh_mcp_server.py"]
    env: {MESH_PRINCIPAL: "rci-vps", MESH_KEY: "/root/.ssh/id_ed25519"}
    timeout: 120
    connect_timeout: 30
```

**googlevps — its own key = roster key `googlevps`:**
```yaml
mcp_servers:
  a2a-mesh-board:
    command: ssh
    args: ["-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
           "-o","HostKeyAlias=100.116.149.122",
           "root@100.116.149.122",
           "MESH_PRINCIPAL=googlevps MESH_KEY=/home/node0datasystems/.ssh/id_ed25519 python3 /opt/mesh-board-prod-20261031/mesh_mcp_server.py"]
```

**Phones (s24 / s21fe / exodus)** — no Tailscale client on S21FE/Exodus; two
working patterns (see `MCP_USAGE.md` for the full discussion): SSH stdio relayed
through the laptop/omega with `MESH_PRINCIPAL=<phone>` (per-phone identity needs
the phone key staged on omega — file-custody caveat, mark trust accordingly), or
direct tailnet HTTP after a Tailscale install (owner decision). No new ports
opened in either pattern.

Tool names as they surface in Hermes:
`mcp_a2a_mesh_board_mesh_post`, `…_mesh_inbox`, `…_mesh_read`, `…_mesh_ack`,
`…_mesh_respond`.

## 5. Roster, fingerprints, and live exchange evidence

6 principals, hub-and-spoke (`rci-vps` hub; spokes post to `rci-vps` only).
Public keys are Ed25519; fingerprints are SHA256 base64 (`ssh-keygen -lf`
format) of the pubkeys embedded in `build_roster_prod.py`:

| Principal | Role | Recipients | rows | rate | Key fingerprint (SHA256) |
|---|---|---|---|---|---|
| `rci-vps` | hub (omega) | all 5 devices | 16 | 8 | `pWMj3IA5mrUXEYpMwAD49PZCZKoH4QQsa+JXQd6b6js` |
| `googlevps` | spoke | rci-vps | 8 | 8 | `hW/agl+VM9FI61PIYInyuoDv68VQswbO0OntJTV7AIw` |
| `s24` | spoke (Termux) | rci-vps | 8 | 8 | `Mrs9IoJ0R+wd0uJtiXVIcI5BtSJwLzTSeuioGcBF8WQ` |
| `laptop` | spoke (jason-parser) | rci-vps | 8 | 8 | `T29TPiU+DJkwRDk9jDrUJxI8I4WRyerz0S8IR8yChow` |
| `s21fe` | spoke (generated on-box 2026-10-31) | rci-vps | 8 | 8 | `5sttVbGSq6e+skLnYtXMlylBqsz1I2H+Nr3NGaqzqLA` |
| `exodus` | spoke (generated on-box 2026-10-31) | rci-vps | 8 | 8 | `qi9cYqaKLCfweRijTyAn3PH7D8cpZngSfApvN/mpFTM` |

`rci-vps`/`googlevps`/`s24` use pre-existing keys (no rotation); `laptop` is the
`mesh-laptop` key already authorized on omega root SSH; `s21fe` + `exodus` were
generated on-device and pulled over pinned SSH.

**Live exchange evidence (2026-10-31):**

- `mcp_exchange_evidence_20261031.json` — PROD-MCP-TEST-1: `rci-vps` MCP
  `mesh_post` → googlevps (direct tailnet HTTP; independent `ssh-keygen -Y`
  verify, durable receipt, ack, signed response) → back to `rci-vps` MCP
  `mesh_read`/`mesh_ack`. Dedupe verified live: a retry of the same content
  returned `dedupe: collapsed` with the original id
  (`22d96849-3fc8-429f-a95b-3f1d9f69a6cb`); re-ack returned `already-acked`;
  inbox empty after ack.
- `mcp_laptop_roundtrip_evidence_20261031.json` — LAPTOP-MCP-ROUNDTRIP: full
  round trip **from the laptop's Hermes** over the configured ssh-stdio MCP
  server (request `d02e30f0-6ddc-407b-88a0-5301b4566d78`, response
  `806dccf1-a73f-4bc6-a351-e652f1a08c2b`): initialize OK, `tools/list` 5 tools,
  `mesh_post`/`mesh_inbox`/`mesh_read`/`mesh_ack` all HTTP 200, googlevps
  verified the request signature, both ends durably receipted + acked, inbox
  empty after ack.
- `revp_sandbox_evidence.json` — the 28/28 no-network container test run
  (returncode 0, with source sha256s pinned).

## Files in this directory

| File | Purpose |
|---|---|
| `board.py` | The production signed board (HTTP, schema v4, port 18792). |
| `mesh_mcp_server.py` | MCP stdio server exposing mesh_post/inbox/read/ack/respond. |
| `build_roster_prod.py` | Builds the production roster (public halves only; refuses diffs). |
| `install_prod.sh` | Idempotent omega installer: bind file + systemd unit + restart + assert. |
| `mesh-board-prod-20261031.service` | Hardened systemd unit (DynamicUser, ProtectSystem=strict, no caps, 128M). |
| `receipt.py` | Networkless receipt boundary: signed bytes stored before ack permitted. |
| `recovery.py` | Offline snapshots, bounded inventory, quarantined restore. |
| `log_redact.py` | Redacts token-shaped strings before any log line. |
| `test_signed.py` | The 28-test sandbox suite. |
| `run_sandbox_revp.py` / `run_sandbox_revb.py` | Trusted operator runners (no-network container). |
| `MCP_USAGE.md` | Per-agent MCP wiring + security invariants (original ops doc). |
| `mcp_exchange_evidence_20261031.json` | PROD-MCP-TEST-1 live exchange evidence. |
| `mcp_laptop_roundtrip_evidence_20261031.json` | Laptop Hermes live round-trip evidence. |
| `revp_sandbox_evidence.json` + `revb_sandbox_evidence_*.json` | Sandbox test-run evidence (28/28 OK). |
