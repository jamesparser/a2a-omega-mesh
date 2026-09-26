# Peer registry

`config/peers.json` (copied from `peers.example.json`) is the hub's address book.
**It holds credentials and is gitignored — never commit the real one.**

Only the fields a peer actually needs are read:

| Transport | Required per peer | Also needs |
|---|---|---|
| AgentVerse | `agentverse_address` | `uagents` SDK + API key in env |
| e2a.dev | `e2a_email` | an e2a account key in env |
| AgentMail | `inbox`, `agent_mail_key` | nothing else |

Anything missing is skipped and the next transport in the chain is tried, so a
peer can be registered with one transport only.

Optional per-peer overrides: `e2a_from`, `agentverse_seed`, and the dormant
MailSlurp path (`mailslurp_inbox`, `mailslurp_email`, `mailslurp_api_key_site`).

`note` is free text for you. The hub ignores it.

Treat this file like a password store: the addresses are real inboxes and the keys
let anyone who has them send mail as your agents.
