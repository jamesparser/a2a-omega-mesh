# A2A Omega Mesh

**Your AI agents don't need you anymore.**

A self-hosted routing hub that lets the agents you run talk to each other — send
work, ask for a second opinion, report that they're finished — without you
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

> Fork of my own [`jamesparser/a2a-omega`](https://github.com/jamesparser/a2a-omega)
> (BGI Commons HyperSprint #2, team 58 — JasonParser Security). This copy is
> packaged for the [Decentralize AI Hackathon](https://decentralizeai.tech) by
> HackerNoon, Nosana, Arweave and MEXC.

---

## Why I built this

I run several agents. Omega lives on a headless VPS and does research. Liberclaw
and Betterclaw run longer jobs. Some have a vision model, some can drive a
browser, one is mostly a code reader.

They were useless to each other.

Every handoff went through me. *Omega found something and wants a second pair of
eyes on the diff* — so I pasted the diff into another terminal. *Liberclaw
finished the task* — so I checked on it, then told Omega. *Betterclaw is idle and
wants work* — so I remembered to ask. *Omega needs something posted from a
logged-in browser, and it is on a headless box with no browser* — so I did the
browser part myself, at 1am, acting as the network cable between two programs I
own.

That isn't intelligence. That's me doing packet routing by hand.

So I put a mailbox in front of each of them and a hub in the middle. Now Omega
sends a task to Betterclaw and gets a reply, and I read a summary in the morning.

## What it does

| | |
|---|---|
| **A2A-shaped endpoint** | `POST /a2a/v1` with `SendMessage`, plus `tasks/get` and `tasks/cancel`. Publishes `/.well-known/agent-card.json` at `protocolVersion` `0.3.0` |
| **Store-and-forward** | Delivery succeeds while the receiver is switched off. Nothing has to be listening for a message to arrive |
| **Rotating transports** | The preferred transport goes first, the rest stay as fallbacks, so one vendor's outage or one missing key never blocks routing |
| **Peer identities, not shared state** | Each agent keeps its own mailbox and its own credentials. No shared database, no persistent connections, no third party holding the whole graph |
| **Task lifecycle** | `submitted → working → completed / failed / canceled`, persisted per peer as JSONL |
| **Daily transcript** | One email a day with what your agents said to each other, so autonomy doesn't mean blindness |
| **Optional push webhook** | JSON task events on terminal state, if you'd rather be told than poll |

## What it is not

It is not a replacement for [Linux Foundation A2A](https://a2a-protocol.org). The
hub deliberately mimics the A2A shape — agent card, `SendMessage`, task methods —
so an A2A client can talk to it. Where it differs is the assumption about who the
agents are.

A2A is a good protocol for agents that run as **online services**: reachable
endpoints, TLS, a port to call. Most personal agents are not that. They run on a
laptop that sleeps, on a secondhand GPU box behind a home router, inside a
container with no inbound route. They don't need a better RPC timeout; they need
the message to still arrive at 4am when nobody is listening.

Email solved that problem in 1971. This uses it again, on purpose, and treats the
transport as replaceable rather than sacred. AgentVerse and e2a aren't email at
all — they're agent-native mailboxes — and that's the point: the hub doesn't care
which kind of inbox a peer has, only that the message lands.

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
database or open a terminal — the hub keeps a task record per peer, and the peer
answers on its own schedule.

**An idle worker asking for work.** Betterclaw has nothing to do, so it sends a
message asking for some. The hub treats an inbound message from a peer like any
other task. This is the bit that felt like magic the first time: the queue started
feeding itself.

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

Check the whole fleet at once — every ordered pair, on every transport you have
configured:

```bash
python mesh_test.py
python mesh_test.py --json results/mesh-$(date +%F).json   # machine-readable
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
  publishing — every example in this repo and in the write-up is rewritten, not
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
results/                   committed mesh run output
docs/SUBMISSION.md         hackathon packaging + what's left to do
```

## License

MIT — see [LICENSE](LICENSE).

*(The original repo's README said GPL-3.0 while its LICENSE file said MIT. Matched
to LICENSE here. If GPL was intended, change both.)*
