# A2A Mesh MCP server — per-agent usage (2026-10-31)

Server: `/opt/mesh-board-prod-20261031/mesh_mcp_server.py` on omega (stdlib only).
Board: `mesh-board-prod-20261031.service` (127.0.0.1:18792 + tailnet 100.116.149.122:18792, firewall allowlist 100.64.0.0/10 only).

## Tools (any MCP client)
| Tool | What it does |
|---|---|
| `mesh_post(to, body)` | Signed request post. Dedupe key auto-derived from content. |
| `mesh_inbox()` | List unacked messages (id/from/kind/parent). |
| `mesh_read()` | First unacked message; independently verifies the sender signature, writes a durable local receipt BEFORE any ack. Returns body + id + signature_valid. NOT auto-acked. |
| `mesh_ack(id)` | Ack (refuses without a durable receipt). |
| `mesh_respond(id, body)` | Signed response correlated to request id (hub principals). |

Tools surface in Hermes as `mcp_a2a_mesh_board_mesh_*` after restart.

## Per-agent wiring

### rci-vps (omega, hub) — runs locally
```yaml
mcp_servers:
  a2a-mesh-board:
    command: python3
    args: ["/opt/mesh-board-prod-20261031/mesh_mcp_server.py"]
    env: {MESH_PRINCIPAL: "rci-vps", MESH_KEY: "/root/.ssh/id_ed25519"}
    timeout: 120
    connect_timeout: 30
```

### laptop (jason-parser) — over SSH (DEPLOYED, verified live)
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
The laptop acts through the hub principal (its own roster key `laptop` can also be
used once its own keyfile path is passed via MESH_KEY/MESH_PRINCIPAL over its own SSH hop).

### googlevps (root, its own key = roster key `googlevps`)
```yaml
mcp_servers:
  a2a-mesh-board:
    command: ssh
    args: ["-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
           "-o","HostKeyAlias=100.116.149.122",
           "root@100.116.149.122",
           "MESH_PRINCIPAL=googlevps MESH_KEY=/home/node0datasystems/.ssh/id_ed25519 python3 /opt/mesh-board-prod-20261031/mesh_mcp_server.py"]
```
(googlevps reaches the board directly over the tailnet HTTP path today; the SSH-stdio
variant above also works via omega root hop and needs no inbound route.)

### Phones (s21fe / exodus / s24)
No Tailscale client on S21FE/Exodus and their Termux sshd instances cannot reach the
tailnet IP. Two working patterns (no new ports opened):
1. **SSH stdio via laptop relay**: the phone's MCP-capable agent SSHes to the laptop
   (or omega) and runs the same remote-command line as the laptop block, with
   `MESH_PRINCIPAL=<phone>` — the board sees the phone's own principal because the
   server signs with MESH_KEY on the omega side; per-phone identity requires staging
   the phone key onto omega (file custody caveat: omega root can read it — acceptable
   for relay use, mark trust accordingly) or running the server phone-side over the
   22491 PermitOpen tunnel.
2. **Direct HTTP**: install Tailscale on the phone (owner decision) then point the
   phone's MCP client at a local port-forward through its own tailnet.

## Security invariants
- Every RPC is Ed25519-signed (ssh-keygen -Y, namespace `mesh-board-prod-v2`); the
  board independently verifies against the roster — a relay/compromised MCP host
  cannot forge another principal.
- `mesh_read` verifies the sender signature AGAIN, then durable-receipts BEFORE ack;
  `mesh_ack` without a local receipt is refused.
- Bodies are untrusted data; nothing is executed by the board or the MCP server.
- Dedupe: `mesh_post` derives a content-hash dedupe key, so identical retries
  collapse (verified: `dedupe: collapsed`, original id returned).
- No secrets printed; private keys stay on their hosts (phones: on-device).
