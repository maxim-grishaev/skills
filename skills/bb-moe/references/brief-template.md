# Briefs

Save each brief as `S/briefs/<name>-NN-<task>.md` (name without `&`) before you send it. `S` is your storage root and `R` is this skill's `references/` directory, both absolute.

A brief carries only what is specific to this agent and task. What a role does, and how the team works, is in the role files under `R/roles/`; do not repeat them. Drop a part only if it truly does not apply.

## Opening of every brief

> You are `&<name>`, <role in one line> for <the piece of work>. The Lead (your parent thread) dispatched you; your final response is reported to the Lead. The user can read this thread and step in; what the user tells you here wins over this brief. Read and follow `R/roles/common.md` and `R/roles/<role>.md`. Storage root: `S`. Weight: <full / light>.

## Roles

| Agent | Role file | Model | Environment | Spawn |
|---|---|---|---|---|
| `&debrief__scout` | `debrief.md` | stronger | your worktree, read-only | first, every job. Weight in its opening: "full unless the user approves light" |
| `&architect` | `architect.md` | stronger | your worktree | after the debrief, full jobs |
| `&arch__skeptic` | `arch-skeptic.md` | stronger | your worktree, read-only | after the user approves the design; stays for the whole job |
| `&<topic>__scout` | `scout.md` | stronger | your worktree, read-only | on an open technical question |
| `&<topic>__build` | `build.md` | mid-tier | new worktree from an exact commit | per topic, first of its group |
| `&<topic>__qa` | `qa.md` | mid-tier | the builder's environment | with the builder |
| `&<topic>__reviewer` | `reviewer.md` | stronger | the builder's environment, read-only | with the builder; the last gate in a light job |
| `&<topic>__review-skeptic` | `review-skeptic.md` | stronger | the builder's environment, read-only | with the builder, full jobs only |
| `&main__qa` | `main-qa.md` | mid-tier | your worktree | when a second topic starts, or when `&butler` asks for it |
| `&butler` | `butler.md` | mid-tier | your worktree | at the first chore, or once landing is allowed, before that topic's agents; stays for the whole job |
| deliverable builder | `delivery.md` | mid-tier | its own worktree | as the last link, when the user needs an artefact |

These are the typical roles. A role not in this table gets its whole job in the brief, and its opening names only `R/roles/common.md`. All models run at `--reasoning-level high`. Command forms: `R/bb-commands.md`.

## What every brief fills in

```markdown
<opening>

## The user's request, word for word

"<exact quote>"

<Your reading, marked as yours, if you interpreted.>

## Background

<Only what the agent cannot find itself: the state of the work, earlier agents' findings (paths to logs and reports), decisions made and by whom, known traps. For repo facts, point to them; do not copy them.>

Read first: <project agent instructions; full job: `S/design/architecture.md`, task `<topic>` in `S/design/roadmap.md`, its ADRs; light job: `S/reports/debrief.md`; earlier agents' logs with working recipes>.

## Your task

<What this agent does beyond its role file: the topic, the question, the chore. Where it decides, the default you want, and when to stop and ask instead.>

## Where you work

<Worktree path and branch, or "read-only in <path>". Who else uses it, and what not to touch (their processes, build output).>

## Limits

- May start: <emulator / dev server / nothing; URL, port, test account file>. Not allowed: <what needs the user's OK>.
- Commit: <no / yes, on your branch>. Push: <no / yes, plain (only `&butler`)>.
- Credentials: <none / `S/secrets/<x>.env`>.

## Proof

<Exact commands, if you know them: installs and one-time setup a fresh worktree needs; format, typecheck, lint, test. Otherwise: "find them in the agent instructions". QA: the acceptance checks, from the roadmap task (full) or from `S/reports/debrief.md` (light).>

## Team

<Peers by name; their thread IDs are in the registry. Max rounds: 3 (5 if exploratory). The chain trigger and the next link, if landing is allowed. Light job, reviewer: "You are the last gate.">

## Final answer

<The shape you want, if it differs from the role file.>
```

Role-specific parts:

- `&debrief__scout`: the request sources (ticket, doc, earlier branches or PRs).
- `&arch__skeptic`: later checks are follow-ups: "Check before dispatch: `S/briefs/<file>`".
- `&butler`: the work branch, its remote and your worktree path; the topics and their builders; `&main__qa` (or "none yet"); the next link after a push (or none); whether it may push.
- `&main__qa`: the check commands; what it may start.
- Deliverable builder: where the artefact goes.

## Follow-up brief

Send a follow-up only for the same task, while the agent's context is small and recent. `&butler`, `&main__qa` and `&arch__skeptic` are the exceptions. Otherwise spawn a fresh agent and point it at this one's log.

```markdown
From the Lead. User: "<exact quote>".

Task: <one paragraph>. Expected state: <branch, HEAD, clean tree>; if different, stop and report.

<Steps, changed limits, proof.>

Final answer: <shape>.
```

## Chain links ("land it when green")

Builder, QA, reviewer and review-skeptic know the review chain from `R/roles/common.md`, "Chains". In the turn the user allows landing:

- Tell the builder it may commit now.
- Tell the last gate (the review-skeptic; the reviewer in a light job) that its pass now goes to `&butler`, not to you. A pass it already gave on the uncommitted tree goes once the builder commits that tree.
- Brief `&butler`, if it does not exist yet.
- If the user needs an artefact, brief the deliverable builder; its trigger is "pushed <SHA>".
