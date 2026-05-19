---
created: 2026-05-19
tags:
- project/auto-review
- decision
status: proposed
---

# 001 — separate periodic-job hosting from agent-runtime hosting

**status**: proposed
**date**: 2026-05-19
**relates to**: `auto-review-906` (north star — single checkin-assembler); `vault-agent/decisions/006-checkin-to-delta-recap` (the pivot that made these workloads deterministic)
**depends on**: nothing — but execution of any consequence depends on the bd issue this ADR opens (host-model discovery)

## context

The auto-review siblings (vault-review, memex-review, agent-review, doctor) all run on openclaw — the OPENCLAW_HOST box that also hosts the openclaw agent runtime and (in `mj@openclaw`) the Hermes agent runtime. The hosting choice was inherited, not chosen: vault-agent was the first periodic job in the family, and it lived on openclaw because openclaw was already where unattended LLM-calling work happened. Its siblings followed the address without re-asking the question.

That choice has slowly stopped fitting. In practice the siblings do not use anything that openclaw-the-platform provides:

- No agent harness — they're plain CLI tools installed via `uv tool`
- No openclaw model dispatch — agent-review calls the Anthropic SDK directly; vault-review and memex-review don't use LLMs at all
- No session/conversation logging into agentsview — they're not interactive
- No workspace mounting — `~/.openclaw/workspace-vault-agent/` is unused by the siblings

What they *do* use is incidental to openclaw-the-platform: a Linux host that's always on, has cron, has `~/.secrets`, and has a vault checkout that auto-syncs from forgejo. If openclaw-the-platform vanished tomorrow but the OPENCLAW_HOST box stayed up, the siblings would not notice.

Meanwhile, hosting the siblings on the same box as the agent runtime conflates two security/scrutiny profiles that genuinely differ:

- **Agent-runtime workloads** (the wild-west case): can hold context, react to events, dispatch models, and exercise a broad tool surface. Blast radius is real — agents can write to the vault on their own initiative, run commands the user did not directly authorize, exfiltrate via tool calls. Warrants serious security review.
- **Periodic deterministic jobs** (the boring case): a wrapper script runs a CLI tool on a schedule. Blast radius is whatever the wrapper does, which is auditable in ~20 lines. Does not warrant agent-platform-tier scrutiny because there is no agent.

The vault-agent ADR-006 pivot (2026-05-10) already crossed this boundary at the workload level — vault-agent stopped being an LLM-deciding agent and became a deterministic git-delta recap. But the hosting never moved. The siblings inherited the address without inheriting the original reason.

The friction this is now producing:

- **Trust-surface conflation.** Any security review of openclaw must account for the siblings, even though the siblings could run anywhere; conversely, hardening the siblings does nothing for the wild-west case.
- **Failure-mode coupling.** The parked-failing vault-agent capture/snapshot jobs (auto-review-815, -cgd) failed because of an `openclaw config get --json models.providers.manifest` call. The siblings don't make that call and have nothing to do with the failure — but they share its log, its host, and its operational story.
- **Mental-model overload.** "Move X off openclaw" is ambiguous across three things: the runtime/platform (where agents live), the CLI tool (config, model dispatch), and the specific machine (OPENCLAW_HOST). Discussions get fuzzy because the noun is overloaded.
- **Question-availability mismatch.** The "ask my notes via agent" perk that openclaw vault-access enables is already served by Gemini Scribe in Obsidian — a tool the user is already using interactively. The vault-on-openclaw read substrate isn't load-bearing for anything specific right now.

## decision

**Periodic-job hosting and agent-runtime hosting are different concerns and should not share a machine by default.**

The auto-review siblings are periodic deterministic jobs. They belong on a host whose purpose is "always-on Linux with cron, credentials, and (where needed) a vault checkout." openclaw-the-platform stays around for the wild-west case (agent runtimes, openclaw config dispatch, session logging) where its value actually lives.

This ADR does **not** pick the destination host, does not specify a migration order, and does not commit to a timeline. It establishes the *principle* — that the conflation is a category error and should be untangled — and opens the discovery work needed to make it actionable.

## why this works

- Restores a clean correspondence between *what a workload does* and *what scrutiny it warrants*. The siblings stop borrowing agent-runtime threat model they don't need; openclaw stops borrowing the operational expectations of boring cron jobs it doesn't deserve.
- De-overloads "openclaw" as a noun. After this is executed, "openclaw" means the agent runtime, not the box, not the periodic-job home.
- Pairs naturally with `auto-review-906` (the assembler north star). Once siblings write only to their own canonical stores and the assembler composes the daily check-in, the hosting question gets simpler — the assembler can live anywhere with vault write access, and the siblings can live anywhere with credential access. The two decisions are independent in principle but compose well in practice.
- Decouples failure modes. A broken openclaw config call stops being something that risks an auto-review section. A broken auto-review wrapper stops being something that shows up in the openclaw operations story.

## what we lose

- **Operational simplicity in the short term.** Today everything runs on one box, with one crontab, one log, one set of credentials. Splitting this is more components to think about, even if each component is simpler.
- **The "free perk" of openclaw being able to read the vault as ambient context.** Some hypothetical future agent on openclaw that wanted vault read access would need to mount it explicitly rather than inherit it. (Mitigated: Gemini Scribe already covers the interactive "ask my notes" case from the user's own machine.)
- **Co-located debugging.** When something breaks, having all the cron output in one log on one box is convenient. Per-tool logs on the new host help but are not the same as everything-in-one-place.

These are real costs and worth respecting — but they're outweighed by the trust-surface and category-error costs of staying conflated, especially as the sibling family is likely to grow.

## what this enables (not commitments)

If accepted, the natural next moves are:

- **Pick a destination host.** Options I can see today: a small Proxmox LXC, a Pi or similar SBC, the dev box itself (with awareness that it's a laptop and may sleep), or some existing always-on machine I don't know about. Each has a different cost/availability profile.
- **Decide migration order.** vault-review (only needs vault read access) and doctor are probably easiest to move first because their dependencies are co-resident with the vault. memex-review (needs CF Access credentials + outbound HTTPS) and agent-review (needs agentsview PG + Anthropic API) need more setup on the new host but are otherwise straightforward.
- **Decide the relationship to 906.** If the assembler is built before this hosting move, the assembler's home becomes the natural destination for the siblings too. If hosting moves first, the assembler design has a simpler trust story to inherit. Order matters and is worth deciding deliberately.
- **Retire the openclaw vault checkout** for the auto-review use case, once siblings have moved. (Separate question from whether to retire it for any other use case openclaw might still have for it.)

## open questions

- **What's the always-on machine landscape?** Specifically: which machines besides openclaw are running 24/7 and have or could have vault access? This is the constraint that most narrows the design space and I (Claude) don't have visibility into it.
- **Is there an openclaw threat model on paper anywhere?** If yes, this ADR's "different scrutiny profile" claim should be checked against it; if no, that's worth knowing too (the absence of an explicit threat model is itself a signal that the conflation has been costing something).
- **Does any current or planned hermes/openclaw workload actually need the vault as a read substrate**, in a way that Gemini Scribe doesn't already cover? If the answer is "no, not really," the case for separation gets stronger and simpler.
- **Order vs. 906.** Should this hosting-split happen before, after, or interleaved with the assembler work? The two are independent in principle but executing them in the wrong order could mean redoing work.

## next step

Discovery work tracked in `auto-review-bre`. That issue must resolve before any migration-execution tasks get filed. Do not file migration-execution issues until the host is picked and the order vs. 906 is decided — those would have unresolved premises and become orphan work.
