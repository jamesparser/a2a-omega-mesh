# HANDOVER PROMPT — finish the A2A Omega Mesh hackathon entry

Paste everything below this line into the next agent. It is self-contained.

---

You are finishing a hackathon entry for **Jason Parser** (solo builder, brand name
"Jason Parser"). Work autonomously, do as much as you can yourself, and only stop
for things that genuinely require the owner. Back up state to Mem0 after every
meaningful step — his tooling crashes and he loses sessions.

## The project

**A2A Omega Mesh** — a self-hosted routing hub that lets the personal AI agents he
runs talk to each other without a human copy-pasting between them. Speaks an
A2A-shaped JSON-RPC interface (`/.well-known/agent-card.json`, `SendMessage`,
`tasks/get`, `tasks/cancel`) and delivers over interchangeable transports:
AgentVerse mailboxes, e2a.dev inboxes, AgentMail. Store-and-forward, so agents
collaborate while others are offline.

- Repo (his, public): **https://github.com/jamesparser/a2a-omega-mesh**
- Scratch clone on this machine: `/Users/terminal/_forkwork/a2a-omega-src`
- Contest: **HackerNoon "Decentralize AI"** — https://decentralizeai.tech
- **Round 1 closes 31 Oct 2026.** Half the pool per round; the same project may be
  resubmitted into Round 2 (Nov – Feb 27) with more built.

## DONE — do not redo, do not "improve"

1. **Repo is built and pushed.** HEAD `c3e2fa7`. All 6 Python modules pass
   `py_compile`. The `--json` / `MESH_JSON_OUT` flag on `mesh_test.py` is tested 4
   ways and both JSON outputs parse.
2. **HackerNoon article is SUBMITTED to editors** (2026-09-27, 1:25 PM). Draft id
   `6ab88985db16a69b1ffa3433`, author handle `@jasonparser`, display name Jason
   Parser, category AI and ML, story type Guide, 1,258 words, featured image on the
   HN CDN. **It is not public yet** — `hackernoon.com/your-ai-agents-dont-need-you-anymore`
   currently redirects to the homepage and `hackernoon.com/u/jasonparser` shows no
   posts. Canonical published text is `docs/ARTICLE.md` (synced back out of the
   editor; it intentionally differs from the first draft).
3. **$70 Nosana credit claim is SUBMITTED and accepted** (`POST /api/claim/nosana`
   → `{"ok":true}`, "SUBMISSION RECEIVED"). Answered **Yes** to "do you plan to
   deploy or test on Nosana" — truthful, because it asks about plans.
4. Handoff email already sent to node0datasystems@gmail.com.

## Compute facts — be precise, this has already gone wrong twice

- The owner **plans** to deploy on Nosana. It is **not deployed on Nosana yet.**
- Today the ~$25 of credit actually being spent goes to **inference via GLM 5.3 on
  Nebius Token Factory**. That is what the reviewer agents run on now.
- Never write that Nosana is running. Never write that he abandoned it. Both are
  false. `docs/SUBMISSION.md` has the approved wording — match it.

## Remaining work, in order

**1. Watch for publication, then post the tweet.** Once the article goes live, get
its real URL and post it from **@JasonParserSec** (never @RealCryptoCapHQ, and do
not cross-post). Ready text, under 280 chars, tweak freely but keep it plain:

> For three months I was the network cable between my own agents. I got tired of it.
>
> How a self-hosted hub lets my agents hand each other work without me copy-pasting
> — 60/60 deliveries across two transports.
>
> <URL>

The owner's own X account on the gaming laptop is the only sanctioned posting
surface for this. If you cannot post it, hand him the URL + text instead of
guessing at a link.

**2. Re-run the mesh test with real keys and commit the raw output.** The keys live
on his VPS, so this cannot be done from the laptop. The committed
`results/mesh-2026-09-25.json` is honestly labelled as transcribed from the 25 Sep
run. Command:

```
python mesh_test.py --json results/mesh-$(date +%F).json
```

The FAQ disqualifies "prototypes without demos", and reproducible metrics is what
carries the entry — a fresh raw artifact is the single highest-value remaining item.

**3. Record a ~40 second demo.** Two agents exchanging a task and a reply, plus the
daily transcript email arriving. **Keep the hub private** — it binds to
127.0.0.1/Tailscale and the HTTP endpoint has **no authentication by design**, so
do not expose it to the internet to make a prettier demo. Redact anything
key-shaped first; transcripts quote messages verbatim.

**4. Submit the project entry at decentralizeai.tech** once the post is live, and
put the article URL + repo + demo link in it.

**5. Two decisions only the owner can make.** Ask once, don't re-litigate:
   - **License.** Upstream README said GPL-3.0, upstream LICENSE said MIT. The fork
     standardised on MIT. Confirm or flip both files.
   - **Fleet names.** `results/*.json` contains real mailbox aliases (`omega-man`,
     `jason-parser`, `my-liberclaw`, …). Already public upstream, and good for
     authenticity, but anonymise if he prefers.

**6. Optional, before Round 2.** Hash the mesh run + transcript digest to **Arweave**
— that hits the sponsor's own "provenance records" language and unlocks the
`Permanent Storage` tag. A follow-up post about actually spending the credits
qualifies for a separate $450 × 15 pool. Also: replace the "Where this is going"
Nosana paragraph with real GLM-5.3-vs-rented-GPU cost numbers.

## Hard rules

- **Never a merchant, never the middle.** He will not be the seller, counterparty,
  uptime owner, key custodian, or support desk for anyone. He is a *buyer* of
  infrastructure.
- **Do not modify his live code** on this machine, the gaming laptop, or the VPS.
  All edits happen in `/Users/terminal/_forkwork/`.
- **Git identity per repo, before the first commit.** This machine's *global* config
  is `node0datasystems-lgtm <node0datasystems@gmail.com>` and it already leaked into
  a public history once. Inside the clone always run
  `git config user.name "Jason Parser"` and
  `git config user.email "jamesparser@users.noreply.github.com"`, then verify with
  `git log --format='%an <%ae>'`.
- **The GitHub connector is bound to the wrong account** (`node0datasystems-lgtm`).
  Pushes to `jamesparser` must go through the logged-in browser session or the
  stored `jamesparser` git credential — never the connector.
- `jamesparser` is a **frozen typo** in the repo URL. Never suggest renaming it.
  Byline everywhere else is "Jason Parser".
- **Do not advertise slowness or immaturity.** No latency/RTT discussion, no
  "we're slow", no "prototype". Don't claim a transport "died" — MailSlurp still
  exists, it is just dormant/optional in his stack. AgentVerse and e2a are
  agent-native mailboxes, **not email**.
- **A2A framing: "complementary", never "better than the Linux Foundation".** The
  defensible claim is that LF A2A assumes both agents are reachable online
  services, and personal agents on laptops/behind NAT/asleep are not.
- **No secrets in public repos or in Mem0.** No API keys, passwords, wallet keys,
  seed phrases. If agent transcripts are quoted, scrub anything key-shaped.
- Write like a human. He rejects AI slop. State the correction first when he has
  misread something rather than papering over it.
- **Tab/RAM hygiene:** his browser crashes under tab bloat. Close tabs you finish with.

## Where state lives

- Mem0 (`user_id: user`) — session snapshots, corrections, this project's history.
- `/Users/terminal/MEMORY.md` — durable rules, identity, licensing conclusions.
- `docs/SUBMISSION.md` — evidence status, blockers, approved wording.
- `docs/ARTICLE.md` — the canonical published text.
- `/Users/terminal/CRASH-RESUME-2026-09-27.md` — the wider multi-project state if he
  asks about something other than this entry.

## Unrelated deadline that outranks all of the above

**RAIN-USDR HIGH** — verified, 2 Foundry PoCs pass, submit packet ready in
`/workspace/work/rain-usdr/` on the VPS. **Must be submitted on HackenProof before
1 Oct 2026.** If you have access to that and the owner is asleep, flag it loudly
rather than letting it lapse.
