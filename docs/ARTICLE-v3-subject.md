# AI Agents Need a Post Office, Not Another RPC

Everyone building a personal agent fleet eventually hits the same wall. You have a research agent on a VPS, a browser agent on a laptop, maybe a code reviewer in a container. They are useful alone. Together they are useless, because they cannot talk to each other unless every side is online at the same time.

That is not a model problem. It is a transport problem. And the usual fix, a remote procedure call, is the wrong shape for it.

## The presence assumption

The Linux Foundation A2A work is a solid protocol. JSON-RPC over HTTPS, agent cards, task methods, gRPC if you want it. It is built for agents that run as services: a port, TLS, somebody answering the phone.

Most personal agents are not services. A laptop that closes at 6pm is not a service. A container with no inbound route is not a service. When you tell one agent to "just call" the other, you have assumed both processes are up, reachable, and authenticated at the same moment. That assumption is false most of the time.

I spent months being the network cable. One agent found something worth filing. I copied the text into a browser on another machine, posted it, and told the first agent it was done. At 1am. More than once. That is store-and-forward done by hand.

## What mail already solved

In 1971 we decided that messages should not require the recipient to be awake. You put the letter in a box. They collect it later. Nobody has to be listening when it arrives.

That is the same requirement personal agents have. Durable handoff. Not streaming chat. Not sub-second RPC. A message that survives the other side being off.

So the useful design is boring: a small hub that speaks an agent-to-agent shape on the outside, and delivers over mailboxes on the inside.

On the outside, keep the protocol familiar. Agent card at a well-known path. SendMessage, tasks/get, tasks/cancel. Any A2A-shaped client can still talk to it.

On the inside, treat every inbox as replaceable. Agent-native mailboxes, real email, whatever the peer actually owns. If one vendor is down, the next door gets the job.

## Trade-offs you should know

**No low-latency chat.** If you want streaming dialogue between two live agents, keep a socket. Store-and-forward is for durable work handoffs.

**No public endpoint unless you own auth.** A hub that trusts whoever can reach the port is fine on loopback or a private network. It is not fine on the open internet. Bind it privately or put real auth in front.

**Transcripts beat dashboards.** Agents talk in prose. If you do not keep a daily digest of what they said to each other, you will not know what happened until something breaks. Autonomy without a summary is negligence with a nicer name.

**Reply correlation is ugly.** Mailboxes do not know your task IDs. Put a task id in the reply body and match on it. Loose, but debuggable at 2am.

## What to measure

Demos are nice. A regenerable number is better.

Write a matrix test. Every ordered pair of agents, every transport you claim to support. Each pair must deliver a task and get a reply. On a six agent fleet that is thirty pairs times two transports. Sixty of sixty is the kind of claim a reader can check.

The property under test is delivery, not intelligence. Can A get work to B when B is not listening? That is the property that makes a personal fleet usable at all.

## The production pattern that stuck

Do not invent a new scheduler. Agents that already poll mail every few minutes can answer A2A tasks in that same loop. The hub keeps task records and matches replies. A worker that runs dry can ask for work. The queue starts feeding itself.

You do not need to be online. You need a digest in the morning.

## If you take one idea away

Protocols that assume both parties are reachable are for services. Agents that sleep need mail semantics: store now, deliver later, keep the transcript.

Once you have that, the interesting work is not the router. It is what the agents say to each other when nobody is copy-pasting between them.

The design above is not magic. It is a post office with a protocol-shaped front door. That is enough to delete the worst part of running a small fleet.
