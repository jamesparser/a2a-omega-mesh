# Submission notes — Decentralize AI Hackathon (HackerNoon / Nosana / Arweave / MEXC)

Entry: **A2A Omega Mesh** — self-hosted A2A routing hub for personal agents.
Repo: https://github.com/jamesparser/a2a-omega-mesh
Byline: **Jason Parser** (the GitHub handle `jamesparser` is a legacy typo; leave it).

## Which round

Round 1 closes **31 Oct 2026**. Half the pool is awarded per round, and the same
project can be resubmitted into Round 2 (Nov-Feb) with more built.

## Claim the credits first (do this today)

https://decentralizeai.tech/claim/nosana - $70 Nosana compute, first 500, and the
form doubles as the project proposal. **One claim per team.** Text to paste:

> A2A Omega Mesh: a self-hosted routing hub that lets personal AI agents send each
> other tasks over interchangeable transports (AgentVerse mailboxes, e2a.dev inboxes,
> AgentMail). Delivery is store-and-forward, so agents collaborate while others are
> offline. Nosana GPUs would run the inference-heavy peers locally instead of renting
> closed APIs - a fleet that owns its transports should also own its compute.
> Planned workload: local open-weight inference for the reviewer / second-opinion
> agent, measured against hosted-API cost.

## Evidence status

| Required by FAQ | Status |
|---|---|
| Working code | done - public repo, full history, MIT |
| Reproducible metrics | done - `results/mesh-2026-09-25.json`, 60/60 deliveries (30 pairs x 2 transports) |
| Deployment URL **or** reproducible metrics | metrics satisfied; a live URL is still missing |
| Demo | **not yet** - hub binds 127.0.0.1/Tailscale, so no public endpoint. Needs a ~40s recording |
| HackerNoon post | drafted, not published |

## Blockers - owner only

1. **Re-run the mesh test** and commit raw output:
   `python mesh_test.py --json results/mesh-$(date +%F).json`
   Keys live on the VPS, so the committed file is transcribed from the 25 Sep run.
2. **Record ~40s of two agents exchanging a task and a reply**, plus the daily
   transcript email arriving. Redact anything key-shaped first - transcripts quote
   messages verbatim.
3. **Decide on a public endpoint.** Recommended: keep the hub private, use the
   recording. A public hub has **no authentication** by design.
4. **Confirm the license.** Upstream README said GPL-3.0 while LICENSE said MIT.
   This fork standardised on MIT. Flip both if GPL was intended.
5. **Fleet names are real mailbox aliases** (`omega-man`, `jason-parser`, ...) and
   already public upstream. Anonymise `results/*.json` if you would rather not.
6. **The Nosana part is intent, not a build.** Do not overstate it in the article.

## Optional, before Round 2

- Hash the mesh run + transcript digest to **Arweave** (sponsor language:
  "provenance records"), and tag `Permanent Storage` for the follow-up post that
  qualifies for the extra $450 pool.
- One paragraph on running a peer's model on Nosana with real cost numbers.
