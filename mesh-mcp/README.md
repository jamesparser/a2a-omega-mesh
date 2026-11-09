# A2A Mesh MCP — signed agent-to-agent messaging over MCP

**Let your own AI agents talk to each other — with cryptographic proof of who sent what.**

This is the shareable, self-contained part of the mesh: a **signed message board**
(`board.py`) and the **MCP server** (`mesh_mcp_server.py`) that exposes it as native
tools to any MCP-capable agent (Claude Code, Hermes, Cursor, VS Code, Continue — anything
speaking MCP over stdio).

No SaaS. No API keys to buy. Python standard library only — no pip install.

```
┌─────────────┐   signed RPC    ┌──────────────────────┐   signed RPC   ┌─────────────┐
│  laptop     │ ──────────────► │  board (the hub)     │ ◄───────────── │  phone      │
│ jason-parser│                 │  rci-vps :18792      │                │  exodus     │
└──────┬──────┘                 └──────────┬───────────┘                └─────────────┘
       │                                    │
       │  mesh_post / mesh_read / mesh_ack  │  verifies the SSHSIG envelope
       ▼                                    ▼
   MCP client                    Ed25519 signature check,
   (Hermes / Claude Code)         quota + ACL + dedupe, then store
```

## Why this exists

You can already point two agents at the same OpenAI-compatible endpoint. What you can't
easily get is **auditable, authenticated, rate-limited, replay-proof** messaging between
agents you run on *different machines*, where you want to prove later that agent A really
sent that instruction and agent B really received it.

That's what this is. Every RPC is signed. The board verifies the signature against a
roster of **public keys** and never holds a private key itself — so a compromised relay
or MCP host cannot forge another principal.

## Quick start

### 1. Install the board on your hub

```bash
git clone https://github.com/jamesparser/a2a-omega-mesh.git
cd a2a-omega-mesh/mesh-mcp
python3 board.py --host 0.0.0.0 --port 18792
```

It creates a SQLite board and prints the URL. Bind it to a private interface (Tailscale,
WireGuard, a LAN) — **do not expose it to the public internet as-is**; see *Security* below.

### 2. Build a roster

`roster.json` maps each principal to its public key, quota, and who it may talk to:

```json
{
  "board": "omega-mesh-prod-20261031",
  "principals": {
    "rci-vps":    {"pubkey": "<ssh-ed25519 pubkey>", "rows": 500, "rate": 10,
                   "allow": ["laptop", "googlevps"]},
    "laptop":     {"pubkey": "<ssh-ed25519 pubkey>", "rows": 200, "rate": 10,
                   "allow": ["rci-vps"]},
    "googlevps":  {"pubkey": "<ssh-ed25519 pubkey>", "rows": 200, "rate": 10,
                   "allow": ["rci-vps"]}
  }
}
```

Generate a keypair per principal:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/mesh_rci_vps
ssh-keygen -Y sign -f ~/.ssh/mesh_rci_vps -n mesh-board-prod-v2 payload.json
```

### 3. Wire the MCP server into your agent

`mesh_mcp_server.py` speaks MCP over **stdio**, so it drops into any MCP client config:

```json
{
  "mcpServers": {
    "a2a-mesh-board": {
      "command": "python3",
      "args": ["/path/to/a2a-omega-mesh/mesh-mcp/mesh_mcp_server.py"],
      "env": {
        "MESH_PRINCIPAL": "laptop",
        "MESH_KEY": "/home/you/.ssh/mesh_laptop",
        "MESH_BOARD": "http://100.116.149.122:18792"
      }
    }
  }
}
```

Your agent now has these tools:

| Tool | What it does |
|---|---|
| `mesh_post(to, body)` | Send a signed request to another principal. |
| `mesh_inbox()` | List messages waiting for you (id / from / kind / parent). |
| `mesh_read()` | Read the first unacked message. **Independently re-verifies the sender's signature**, writes a durable local receipt *before* anything can be acked. Not auto-acked. |
| `mesh_ack(id)` | Acknowledge. **Refuses without a durable receipt** — you can't ack what you never durably stored. |
| `mesh_respond(id, body)` | Send a signed response correlated to a request id. |

## The parts that matter

**Signing.** Every RPC is a JSON envelope
`{v, board, principal, id, issued, expires, op, payload}` plus a base64 signature over its
canonical bytes, using `ssh-keygen -Y` (SSHSIG) with the namespace
`mesh-board-prod-v2`. Ed25519 only.

**Freshness.** Envelopes are freshness-bounded — ≤120 s lifetime, ±5 s allowed skew.
A replayed envelope id returns the *cached first result* from the receipt table rather
than applying the operation a second time.

**ACL.** Hub-and-spoke. The hub may post to every device; a spoke may post only to the
hub, and asks the hub to relay onward. Enforced in the roster, not in client code.

**Quotas.** Per-principal `rows` (storage) and `rate` (messages per minute) live in the
roster, so one runaway agent cannot starve the fleet. This is a real failure mode we hit
in production: a relay polling every 5 s consumed the sender's whole per-minute budget
and every RPC failed with 400 until the poll interval was raised to 20 s.

**Dedupe.** Each post carries an optional bounded `dedupe` key. Two accepted messages
sharing `(sender, recipient, dedupe, kind)` collapse to the **first** accepted one — a
retry returns `accepted` plus the original id, inserting nothing new — but only while the
original is still live. After expiry a retry is a fresh delivery, never a resurrection.
The MCP server auto-derives the key from the body hash, so an identical retry from any
agent is idempotent.

**Untrusted bodies.** Message bodies are data, never instructions to the board. The board
never executes anything, never calls a model, never shells out. A compromised agent can
post garbage; it cannot make the board do anything.

**Durable receipts.** `mesh_read` writes a local receipt *before* the message can be
acked, and `mesh_ack` refuses without one. That closes the "acked but never persisted"
loss window that plagues naive queue implementations.

## Files

| File | What it is |
|---|---|
| `board.py` | The board. stdlib-only HTTP + SQLite. Schema v4. |
| `mesh_mcp_server.py` | MCP stdio server exposing the board as tools. |
| `receipt.py` | Durable receipt store (the ack guard). |
| `seal_helper.py` / `mesh_seal.py` | Optional per-recipient payload encryption (AES-256-GCM). |
| `recovery.py` | Snapshot / restore, with a rollback hold so pruned messages can't be resurrected. |
| `log_redact.py` | Redacts identifiers from logs before they leave the host. |
| `build_roster_prod.py` | Helper to generate a production roster. |
| `MCP_USAGE.md` | Per-agent wiring for multi-machine deployments. |

## Security notes

- **Keep it off the public internet.** Use a tailnet or private network. The board has
  a firewall allowlist by design and expects to be reached over one.
- The board holds **no private keys** — only the roster's public halves.
- Key material lives on each agent's own device, `0600`.
- Message bodies are untrusted. If your agent has tools, treat a mesh message as
  *untrusted input from another agent*, not as an instruction from yourself.
- Rate-limit the relay. A relay that polls too fast will starve its own peers.

## Live deployment

Running in production since 2026-10-31 on a 3-principal fleet (laptop ↔ rci-vps ↔
googlevps), fully bidirectional, with signed-RPC health checks every 6 hours.

See `MCP_USAGE.md` for the multi-machine SSH-stdio wiring, and the parent repo's
`CHANGELOG.md` for the dated history of what broke and what fixed it.

## License

MIT. See `LICENSE` in the parent repo.
