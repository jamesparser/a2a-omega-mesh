# kanban-mcp

Durable per-agent task board (kanban) MCP server and signed/encrypted relay.

## Files
- `kanban_mcp_server.py` - MCP server exposing kanban_create/claim/move/comment/get/list/board/history
- `kanban_board.py` - the board itself (SQLite, signed transitions)
- `kanban_enc.py` / `mesh_enc.py` - per-recipient encryption helpers
- `omega_kanban_relay.py` - host-side relay between the board and the agent container spool
- `lane_kanban_bridge.py` / `gvps_kanban.py` - lane bridges
- `roster.json` - principals and their public keys (PUBLIC keys only)
- `gen_kanban_cek.py` / `install_kanban_cek.py` - generate and install the board CEK
- `kanban-board.service` / `omega-kanban-relay.service` - systemd units

## Secrets
The board CEK lives in `kanban_cek.json` and is NEVER committed. Generate it
with `gen_kanban_cek.py` on each device and install it with
`install_kanban_cek.py`.

## What else is required to make it work

Wiring the MCP block is the easy half. Verified checklist:

**Per lane / client host**

- Its OWN ed25519 signing keypair, public key registered in `roster.json` for
  that principal (`ssh-keygen -t ed25519 -f kanban_principals/<principal>.key`).
- The shared CEK (`kanban_cek.json`, mode 0600) and `kanban_enc.py`. The board
  never holds the CEK; no CEK = every create/read fails CLOSED.
- `ssh-keygen` on PATH (that is what signs envelopes) and an ssh key that
  reaches the board host with `BatchMode=yes`.
- An AES-GCM backend: `pycryptodome` or `cryptography` (`pycryptodome` on Termux).
- `KANBAN_ROSTER` / `KANBAN_DB` are **board-host paths**, not local paths --
  pointing them at `C:/...` makes the board die with `FileNotFoundError: roster.json`.

**Board host**

- `kanban_board.py` + live `roster.json` at `/opt/mesh-board-prod-20261031/`,
  `kanban_mcp_server.py` + `kanban_enc.py` + `kanban_cek.json` (0600) at `/opt/kanban-mcp/`,
  DB at `/var/lib/mesh-kanban/kanban.db` created by `--init`.
- `kanban-board.service` enabled, sshd reachable.

**Skills the agent must have loaded** (code does not need them, the operator does):
`omega-mesh-mcp` (calling the a2a MCP, envelope model), `a2a-omega-mesh` (fleet
topology / which host runs what), `a2a-fleet-ops` (hub + pollers), and
`a2a-brain-bridge-ops` if the brain side of the mesh is being patched. A lane
with the MCP wired but no `omega-mesh-mcp` skill improvises envelopes and gets
rejected.

**Pollers / daemons -- without these the board is a dead mirror**

| Where | Process | Cadence | Role |
|---|---|---|---|
| board host | `kanban-board.service` | oneshot at boot | schema init + receipt prune; cards never expire |
| board host | `omega-kanban-relay.service` | 20 s loop | container spool <-> board, signs as `rci-vps` |
| laptop | `Hermes_Lane_Dispatch` (schtasks, 4 h) -> `dispatch_all.py` -> `kanban_bridge.py` | 4 h | mirrors lanes.md PENDING/DOING/CLOSED onto cards |
| googlevps | `gvps_kanban.py` | on demand | UNION verification lane claims/verifies |
| any lane | MCP tools | on demand | lane records progress on the card it was given |

If `dispatch_all.py` is not running, no cards get created and the board looks
dead even though every lane can read it.

**Preflight** -- run before wiring a profile, and whenever a lane "cannot see
the board": `python kanban_doctor.py --live`. Nine checks: AES backend,
ssh-keygen, signing key + CEK present and 0600, key matches the roster entry,
ssh reaches the board, a signed `kanban_list` returns, and a card body
decrypts. Exit 0 = green. Verified green 2026-11-12 against the live board
(14 cards visible, principal `lane-coding`).

Full install / wiring / troubleshooting (incl. the fixed-bug table: comment
IntegrityError, list-has-no-detail, spool perms, payload defaults, inbound
refresh) lives in the private repo **`jamesparser/a2a-omega-kanban`**.
