# A2A Omega Mesh

**Your AI agents don't need you anymore.**

A self-hosted routing hub that lets the agents you run talk to each other: send
work, ask for a second opinion, report that they're finished, without you
copy-pasting between them.

It speaks an A2A-shaped JSON-RPC interface and delivers over several transports:
[AgentVerse](https://agentverse.ai) agent mailboxes, [e2a.dev](https://e2a.dev)
agent inboxes, and plain email via [AgentMail](https://agentmail.to). If one
transport stops working for a peer, the hub quietly tries the next.

```
jason-parser ──┐
omega          ├──► [ hub ] ──► any peer, over whichever transport accepts it
liberclaw ─────┘                + a daily transcript to you
```

> **This is the active repo.** Development continues here and nowhere else.
> [`jamesparser/a2a-omega`](https://github.com/jamesparser/a2a-omega) is the
> original (BGI Commons HyperSprint #2, team 58, JasonParser Security). It is
> frozen and kept for history; its answering-loop fixes were ported into this
> repo on 2026-10-02 and are not going back.
>
> Packaged for the [Decentralize AI Hackathon](https://decentralizeai.tech) by
> HackerNoon, Nosana, Arweave and MEXC. Round 1 is this repo as it stands;
> [`## Roadmap: v2`](#roadmap-v2) is the Round 2 entry.
>
> Dated history of what broke and what fixed it: [`CHANGELOG.md`](CHANGELOG.md).

---

## Why I built this

I run several agents. Omega lives on a headless VPS and does research. Liberclaw
and Betterclaw run longer jobs. Some have a vision model, some can drive a
browser, one is mostly a code reader.

They were useless to each other.

Every handoff went through me. *Omega found something and wants a second pair of
eyes on the diff*, so I pasted the diff into another terminal. *Liberclaw
finished the task*, so I checked on it, then told Omega. *Betterclaw is idle and
wants work*, so I remembered to ask. *Omega needs something posted from a
logged-in browser, and it is on a headless box with no browser*, so I did the
browser part myself, at 1am, acting as the network cable between two programs I
own.

That isn't intelligence. That's me doing packet routing by hand.

So I put a mailbox in front of each of them and a hub in the middle. Now Omega
sends a task to Betterclaw and gets a reply, and I read a summary in the morning.

## What it does

| | |
|---|---|
| **A2A-shaped endpoint** | `POST /a2a/v1` with `SendMessage`, plus `tasks/get` and `tasks/cancel`. Publishes `/.well-known/agent-card.json` at `protocolVersion` `0.3.0` |
| **Broadcast to the fleet** | `Broadcast` (or `SendMessage` with peer `*` / `all`) fans one message out to every other peer. Each target gets its own task id under a shared `broadcast` id. `python a2a_client.py broadcast "text"` |
| **Cron-ready inbox check** | `python a2a_client.py check` prints `NEW_TASKS=n` and exits 1 when there is new work, 0 when idle. Optional shell helper. Does not replace existing agent pings |
| **Store-and-forward** | Delivery succeeds while the receiver is switched off. Nothing has to be listening for a message to arrive |
| **Rotating transports** | The preferred transport goes first, the rest stay as fallbacks, so one vendor's outage or one missing key never blocks routing |
| **Peer identities, not shared state** | Each agent keeps its own mailbox and its own credentials. No shared database, no persistent connections, no third party holding the whole graph |
| **Task lifecycle** | `submitted → working → completed / failed / canceled`, persisted per peer as JSONL |
| **Daily transcript** | One email a day with what your agents said to each other, so autonomy doesn't mean blindness |
| **Optional push webhook** | JSON task events on terminal state, if you'd rather be told than poll |

## What it is not

It is not a replacement for [Linux Foundation A2A](https://a2a-protocol.org). The
hub deliberately mimics the A2A shape: agent card, `SendMessage`, task methods,
so an A2A client can talk to it. Where it differs is the assumption about who the
agents are.

A2A is a good protocol for agents that run as **online services**: reachable
endpoints, TLS, a port to call. Most personal agents are not that. They run on a
laptop that sleeps, on a secondhand GPU box behind a home router, inside a
container with no inbound route. They don't need a better RPC timeout; they need
the message to still arrive at 4am when nobody is listening.

Email solved that problem in 1971. This uses it again, on purpose, and treats the
transport as replaceable rather than sacred. AgentVerse and e2a aren't email at
all, they're agent-native mailboxes, and that's the point: the hub doesn't care
which kind of inbox a peer has, only that the message lands.

### Why not a Telegram group chat

A group chat is one room. Everyone sees everything, history is shared, and the
platform owns delivery. That is the opposite of what a fleet of personal
agents needs:

| | Agent group chat | This hub |
|---|---|---|
| Identity | one shared window | each agent keeps its own mailbox and address |
| Privacy | every member reads every message | a task goes to the peer it was addressed to |
| Offline agents | messages scroll away unread | store-and-forward holds them until the agent polls |
| Accountability | who did what is anyone's guess | per-peer task lifecycle, `submitted -> working -> completed` |
| Failure | one platform, no fallback | transport chain `agentverse -> e2a -> agentmail` |

Onboarding is the same for every agent, including ones locked inside other
ecosystems. Give the agent an Agentverse mailbox, a free e2a.dev inbox or an
AgentMail inbox, add it to `config/peers.json`, done. WeChat-only Chinese
agents (MaxClaw, QClaw, KimiClaw, Xiaowei) join exactly the same way, and so
do western agents tied to Slack, WhatsApp or Telegram. No chat-app account is
required anywhere in the stack, and no agent has to expose a chat app to work
the fleet.

## Scenarios that actually happened

**Cross-hardware capability.** Omega is on the VPS, headless. It found something
worth publishing, but posting needs a logged-in browser, which it does not have.
Omega sends a task to an agent that *can* drive a browser. The task queues in that
agent's mailbox, the agent picks it up, does it, replies. I was asleep.

**Second opinion on a finding.** Omega drafts a vulnerability report and wants it
checked before anything goes out. It messages another agent the draft and the PoC.
The reply comes back with the case that breaks the PoC. Two agents, one false
positive removed, no human in the relay.

**Chasing a job.** I want to know whether Liberclaw finished. I don't query a
database or open a terminal: the hub keeps a task record per peer, and the peer
answers on its own schedule.

**An idle worker asking for work.** Betterclaw has nothing to do, so it sends a
message asking for some. The hub treats an inbound message from a peer like any
other task. This is the bit that felt like magic the first time: the queue started
feeding itself.

## Transport precedence

`A2A_TRANSPORT` picks the primary (default `agentverse`). The hub always falls
back through the same canonical order, so a missing key or SDK never blocks
routing:

1. **Agentverse**: `POST https://agentverse.ai/v2/agents/mailbox/submit` (signed Envelope, Bearer JWT)
2. **e2a**: `POST https://api.e2a.dev/v1/agents/{from}/messages` with `{"to":[...],"subject","text"}`
3. **AgentMail**: last resort, per-peer `inbox` + `agent_mail_key`

A transport the peer cannot use is dropped (no `agentverse_address` / no
`e2a_email` / no `agent_mail_key`); the order of the rest is preserved.
MailSlurp was removed as a 4th fallback on 2026-09-25, because e2a and Agentverse both
passed the full 6-agent mesh, so the extra hop only added an unused
sandbox-inbox dependency.

e2a needs a browser-like `User-Agent` (Cloudflare 1010 otherwise). Peers carry `e2a_email` + `agentverse_address` in `config/peers.json`.

### The hub must sign as a registered identity

`a2a_agentverse.py` signs outbound envelopes with `A2A_AGENTVERSE_SEED`, which
defaults to `A2A_SEED_PREFIX + A2A_HUB_IDENTITY` (= the `jason-parser` fleet
identity). **Do not point it at an ad-hoc seed.** An unregistered signing
identity has no mailbox, so every agent that tries to answer a hub-sent task
gets `404 Target agent not found` and the answer is silently lost. The poller
defends against this too: on a 404 it redirects the answer to
`A2A_REPLY_FALLBACK` (default `jason-parser`) instead of dropping it.

## Before you install: your identities, not ours

Running this repo does **not** connect you to the maintainer's agents, and it
cannot send prompts to them. Nothing here defaults to a real fleet.

Earlier revisions did, and that was a genuine defect, not a style choice. A
fresh clone would:

- sign Agentverse envelopes with the maintainer's registered seed, so its tasks
  arrived looking like they came from someone else's agent, and the replies to
  them landed in the maintainer's mailbox instead of yours;
- redirect every undeliverable answer into the maintainer's mailbox;
- mail fallback-lane status reports to the maintainer's AgentMail inbox;
- start a poller for an agent name it did not own, competing for that mailbox.

All of that is gone. The current behaviour:

| Setting | Default now | If you leave it unset |
|---|---|---|
| `A2A_HUB_IDENTITY` / `A2A_SEED_PREFIX` | none | `av_send` refuses to sign and returns an error explaining what to set |
| `A2A_OWN_AGENTS` | none | `omega_poller.py` exits 2 and tells you to name your own agents |
| `A2A_FLEET` | `agent-one,agent-two,agent-three` | broadcast only reaches placeholder names that resolve to nothing |
| `A2A_REPLY_FALLBACK` | none | redirection disabled; an answer to an unregistered sender is dropped loudly in the log, not mailed to a stranger |
| `LCB_REPLY_TO` | none | fallback-lane statuses are logged, not mailed |
| `A2A_HUB_SENDER_E2A` | none | the e2a lane has no sender and will not transmit |

Copy [`config/fleet.env.example`](config/fleet.env.example) to
`notes/fleet.env` and fill in your own agents. That path is gitignored, so your
identities stay local. Both `deploy/run_poller_one.sh` and
`deploy/omega_poller_keeper.sh` source it automatically.

The rule this enforces: **identity is input, never a default.** A routing hub
that guesses who you are will eventually speak as someone else.

## Quick start

Python 3.9+ (verified compiling on 3.9.6). Standard library only for the email path; `uagents` is needed only
for the AgentVerse transport.

```bash
git clone https://github.com/jamesparser/a2a-omega-mesh
cd a2a-omega-mesh
cp .env.example .env          # the inbox you send from, and its key
cp config/peers.example.json config/peers.json
python a2a_hub.py             # binds 127.0.0.1:8787
```

Send a task to a peer:

```bash
curl -X POST http://127.0.0.1:8787/a2a/v1 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage",
       "params":{"message":{"parts":[{"text":"[a2a] review this diff before I file it"}],
                            "sender":"omega"},
                 "peer":"betterclaw"}}'
```

Have an agent drain its own mailbox and reply:

```bash
A2A_ME_INBOX=betterclaw@example.com A2A_HUB=http://100.x.y.z:8787 python a2a_client.py poll
```

Check the whole fleet at once: every ordered pair, on every transport you have
configured:

```bash
python mesh_test.py
python mesh_test.py --json results/mesh-$(date +%F).json   # machine-readable
```

## Add another agent

1. Give the agent its own inbox on one of the transports (AgentVerse, e2a.dev, or AgentMail).
2. Open `config/peers.json` and add a block with the peer name you want other agents to use.
3. Fill only the fields that transport needs. See `config/README.md`.
4. Reload is free: the hub re-reads `peers.json` on every routing call. No restart required.
5. Prove it: `python mesh_test.py` or send one task with `SendMessage`.

Example peer entry:

```json
"new-agent": {
  "e2a_email": "new-agent@agents.e2a.dev",
  "note": "research peer"
}
```

Agents do not need a public URL. They need an inbox the hub can write to and a way to read that inbox later.

## Keep agents picking up work

Store-and-forward means a message can sit in a mailbox until some process reads it.
On a real fleet that process is usually a short poll on a timer.

Recommended for installers: every agent runs a poll about every 5 minutes.

```bash
# crontab -e on the machine that owns that agent
*/5 * * * *  cd /path/to/a2a-omega-mesh && A2A_ME_INBOX=you@example.com A2A_HUB=http://127.0.0.1:8787 python a2a_client.py poll >> /tmp/a2a-poll.log 2>&1
```

If you already have agent loops that check mail, keep them. Do not stack a second
poller on top. `a2a_client.py check` is only there if a shell exit code is useful.

Optional fleet fan-out:

```bash
python a2a_client.py broadcast "status note for everyone"
```

### The answering loop: `omega_poller.py`

One process per agent, each with its own brain slot, persona and ledger:

```bash
A2A_AGENTVERSE_ENV=/path/agentverse.env \
A2A_OWN_AGENTS=omega-man \
A2A_ANSWER_BASE=http://127.0.0.1:4000/v1 \
A2A_ANSWER_KEY=... A2A_ANSWER_MODEL=... \
python3 omega_poller.py __actor=omega-man
```

Every `[a2a]` message gets a real answer:

| Message | How it is answered |
|---|---|
| status-shaped (`working on`, `queue`, `need work`) | from that agent's **own ledger**, so it is grounded and cannot confabulate |
| anything else | through that agent's **own brain slot**, with its persona + live ledger injected as context, so it answers as itself |
| `start your top task` directive | pulls the top of its own queue into `active` and confirms it (closed loop) |
| brain unreachable | says so explicitly; it does **not** invent an answer |

**One process per agent, always.** `__actor=<name>` narrows a process to a
single agent. Running one process with a multi-name `A2A_OWN_AGENTS` *alongside*
per-actor processes puts two pollers on every mailbox, racing on the same
`.av_seen_<agent>.json`, which duplicates answers and can resurrect an envelope
the other process already handled.

A message that cannot be delivered is retried up to `A2A_MAX_ATTEMPTS` (default
3) and then dropped loudly, so one bad envelope can never block a mailbox.
Per-message exceptions are isolated and the dedupe state is persisted in a
`finally` block.

### Supervision: `deploy/`

`deploy/omega_poller_keeper.sh` + `deploy/omega-a2a-poller.service` run one actor
per agent under systemd: they start missing actors, **kill duplicate and legacy
catch-all pollers**, and self-heal the uagents SDK after a container recreate.
`deploy/README.md` covers topology and install; `deploy/status-check.ps1` is a
read-only health check for the Windows side.

Verify the fleet actually answers end to end:

```bash
python3 deploy/verify_answers.py --wait 90      # 6/6 REAL ANSWER expected
```

## Does it work

Yes, on a six-agent fleet. `mesh_test.py` walks every ordered pair (30 of them)
and requires each to receive and reply on both the e2a and AgentVerse transports.

The 2026-09-25 run: **60 of 60 deliveries succeeded** (30 ordered peer pairs, each
on both transports), zero failures. Machine-readable result in
[`results/mesh-2026-09-25.json`](results/mesh-2026-09-25.json).


The property under test is **delivery**, not responsiveness: can agent A get a task
to agent B when B is not currently listening. That is the thing that makes a fleet
of personal agents usable.

## Tests

```bash
python3 test_omega_poller.py        # answering loop, retry bounds, 404 redirect, actor scoping
python3 test_a2a_hub.py             # transport chain agentverse -> e2a -> agentmail
python3 deploy/test_lcb_responder.py  # AgentMail fallback lane, single-instance lock
```

## Roadmap: v2

Round 1 of the Decentralize AI Hackathon is this repo as it stands. The same
project can be resubmitted into **Round 2 (Nov 2026 to Feb 2027)** with more
built, so v2 is planned against that window.

**Planned for v2, in order:**

1. **Reply-aware escalation.** Today the transport chain falls back on *send*
   failure only. v2 adds a delivery-then-answer state machine: a task counts as
   answered only when the receiving agent confirms it received the message and
   returns a reply, including a plain working-on-it status while the work runs.
   A task that was delivered but never answered escalates to the next lane or
   back to the operator instead of sitting at `completed` forever. This is the
   blocker for paid work, because you cannot bill for a task you cannot prove
   was answered.
2. **Durable queue.** A lane outage parks outbound messages and drains them on
   recovery instead of reporting failure and moving on. The honesty of
   `lcb_responder.py` stays: when its forward back into Agentverse fails it
   still replies `not_answered` rather than faking success. The queue turns
   that honesty into durability, so the message survives instead of being gone.
3. **Proof-of-work receipts.** Generalise `deploy/verify_answers.py` into a
   signed, timestamped receipt per task: what was asked, which agent answered,
   how long, and the answer itself. The receipt is the settlement record for
   the paid-jobs loop and the audit trail for everything else.
4. **MCP server.** Expose the hub as tools (`send`, `broadcast`, `task_status`,
   `read_transcript`, `fleet_health`) so any MCP-capable client can drive the
   fleet without learning the JSON-RPC shape. The interface is free; the
   supervised backend behind it is the product.
5. **More agent harnesses.** The poller currently speaks Agentverse natively.
   v2 adds adapters so other harnesses join the fleet as first-class peers,
   each keeping their own brain slot, persona and ledger. Agents locked inside
   other ecosystems do not need a bridge to take part: a WeChat-only Chinese
   agent (MaxClaw, QClaw, KimiClaw, Xiaowei) or a Slack-bound western agent
   joins by getting one of the three accounts this hub already speaks, an
   Agentverse mailbox, an e2a inbox or an AgentMail inbox, plus one line in
   `config/peers.json`. No Telegram, WeChat, WhatsApp or Slack integration is
   required anywhere in the stack.
6. **More fallback lanes, and lane symmetry.** Additional transports behind
   agentmail, each held to the same delivery-then-answer standard.
7. **Job intake and subcontracting.** Accept a job on Agentverse, split it
   across the fleet, aggregate the answers, deliver one result, report the
   split, settle against receipts. The orchestration already exists (broadcast
   plus per-agent brains); what is missing is the intake and settlement side.

**Explicitly not planned:** chat-app integrations. The hub routes over
Agentverse, e2a and AgentMail and never through Telegram, WhatsApp, WeChat or
Slack. A new agent, whatever ecosystem locked it in, joins by getting one of
those three accounts. That is the whole onboarding.

## Security notes

Read these before running it anywhere.

- **The hub trusts whoever can reach the port.** Bind `127.0.0.1` or a private
  network (Tailscale `100.x.y.z`). Never `0.0.0.0` on a public interface. The
  HTTP endpoint has no authentication because it was never meant to face the
  internet.
- **Secrets stay out of git.** Keys come from `.env`, the environment, or a local
  vault helper. `tasks/`, `inbox/`, `config/peers.json` and `.env` are gitignored;
  the committed `peers.example.json` uses obviously fake placeholders.
- **Transcripts contain your agents' words.** If a peer pastes an API key into a
  message, the daily transcript will happily mail it to you. Redact before
  publishing: every example in this repo and in the write-up is rewritten, not
  raw.
- **Email is not a confidential channel.** These transports give you delivery and
  provenance, not secrecy. Encrypt the payload if the content matters.
- **You are the operator.** Every identity in the fleet is yours, on services you
  signed up for. Free tiers bite: two free e2a accounts gave three agents each,
  which is exactly why this fleet is six and not sixty.

## Layout

```
a2a_hub.py                 routing server: A2A-shaped RPC, transports, transcript
a2a_client.py              one agent: poll its inbox, send to peers
a2a_agentverse.py          AgentVerse mailbox transport (uagents, signed envelopes)
a2a_e2a.py                 e2a.dev inbox transport
mesh_test.py               NxN delivery test across transports, optional JSON output
poller.py                  watch inboxes, forward notable mail to the owner
config/peers.example.json  peer registry template (placeholders)
config/README.md             which fields each transport actually needs
config/fleet.env.example    template for your local, gitignored fleet identity
omega_poller.py             per-agent answering loop: own brain slot, persona, ledger
test_omega_poller.py        regression tests for the answering loop and its failure modes
test_a2a_hub.py             transport chain tests (agentverse -> e2a -> agentmail)
deploy/                     supervision: keeper script, systemd unit, responder, verifier
results/                   committed mesh run output
docs/SUBMISSION.md         hackathon packaging + what's left to do
CHANGELOG.md               dated revision timeline: what broke, what fixed it
```

## License

MIT, see [LICENSE](LICENSE).

*(The original repo's README said GPL-3.0 while its LICENSE file said MIT. Matched
to LICENSE here. If GPL was intended, change both.)*
