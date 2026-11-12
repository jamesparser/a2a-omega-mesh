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
