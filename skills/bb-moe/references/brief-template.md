# Briefs

`moe-lead.py brief` renders and saves each first brief as `S/briefs/<name>-NN-<task>.md` (name without `&`); `python3 <skill>/scripts/moe-lead.py brief --help` lists its flags. `S` is your storage root and `R` is this skill's `references/` directory, both absolute.

A brief carries only what is specific to this agent and task. What a role does, and how the team works, is in the role files under `R/roles/`; do not repeat them. Drop a part only if it truly does not apply.

## What `moe-lead.py` writes

- The opening: the agent's name and role, `--task`, your thread ID, that its finished turns do not reach you, the role files to read, `S` and the weight.
- After your body: `## Where you work` (the environment by role), `## Limits` (`--start`, `--commit`, `--push`, `--creds`) and `## Team` (your thread, `--works-for`, `--peers`, with their thread IDs from `S/logs/team.json`).

## Roles

| Agent | Role file | Model | Environment | Spawn |
|---|---|---|---|---|
| `&debrief__analyst` | `debrief.md` | stronger | your worktree, read-only | right after its scout. Weight as for the scout |
| `&debrief__scout` | `scout.md` | mid-tier | your worktree, read-only | first, every job, working for the analyst. Weight in its opening: "not set yet; the Lead sets it after the debrief" |
| `&architect` | `architect.md` | stronger | your worktree | after the debrief, full jobs, or when the user moves a light job to full for an ADR; stays for the whole job, for later design changes and builders' ADRs |
| `&arch__skeptic` | `arch-skeptic.md` | stronger | your worktree, read-only | after the user approves the design; stays for the whole job |
| `&<topic>__scout` | `scout.md` | mid-tier | your worktree, read-only | right before the agent it works for, when you expect that agent to need legwork; or later, when it asks |
| `&<topic>__build` | `build.md` | mid-tier | new worktree from an exact commit | per topic, first of its group |
| `&<topic>__qa` | `qa.md` | mid-tier | the builder's environment | when the builder reports "ready for QA" |
| `&<topic>__reviewer` | `reviewer.md` | stronger | the builder's environment, read-only | when QA passes; the last gate in a light job |
| `&<topic>__review-skeptic` | `review-skeptic.md` | stronger | the builder's environment, read-only | when the reviewer's findings are in, full jobs only |
| `&main__qa` | `main-qa.md` | mid-tier | your worktree | when a second topic starts, or when `&butler` asks for it |
| `&butler` | `butler.md` | mid-tier | your worktree | at setup, every job; stays for the whole job |
| deliverable builder | `delivery.md` | mid-tier | its own worktree | after `&butler` pushes, when the user needs an artefact |

These are the typical roles; `moe-lead.py --role` takes each role file's name without `.md`, and its `ROLES` table mirrors this one: change both together. A role not in this table is `--role custom`, with `--what`, `--tier` and `--env`; its brief gives its whole job, and its opening names only `R/roles/common.md`. The Model column names a tier; the tier map in `S/logs/team.json` gives its model ID. Every spawn runs at `--reasoning-level high`.

## The body you write

Pipe it to `moe-lead.py brief` on stdin, through a quoted heredoc (`<<'EOF'`).

```markdown
## The user's request, word for word

"<exact quote>"

<Your reading, marked as yours, if you interpreted.>

## Background

<Only what the agent cannot find itself: the state of the work, earlier agents' findings (paths to logs and reports), decisions made and by whom, known traps. For repo facts, point to them; do not copy them.>

Read first: <project agent instructions; full job: `S/design/architecture.md`, task `<topic>` in `S/design/roadmap.md`, its ADRs; light job: `S/reports/debrief.md`; earlier agents' logs with working recipes>.

## Your task

<What this agent does beyond its role file: the topic, the question, the chore. Where it decides, the default you want, and when to stop and ask instead.>

<What not to touch in the shared worktree, if anything: other agents' processes, build output. `--start` names what it may start: emulator, dev server, URL, port, test account file.>

## Proof

<Exact commands, if you know them: installs and one-time setup a fresh worktree needs; format, typecheck, lint, test. Otherwise: "find them in the agent instructions". QA: the acceptance checks, from the roadmap task (full) or from `S/reports/debrief.md` (light).>

## Chain

<The trigger message, and the next link, if landing is allowed; the chain itself is in `R/review-chain.md`. Light job, reviewer: "You are the last gate." Put the peers in `--peers`.>

## Final answer

<The shape you want, if it differs from the role file.>
```

Role-specific parts:

- `&debrief__analyst` and `&debrief__scout`: the request sources (ticket, doc, earlier branches or PRs).
- Every scout: `--works-for <agent>`. That agent's brief has the scout in `--peers`.
- `&arch__skeptic`: later checks are follow-ups: "Check before dispatch: `S/briefs/<file>`".
- `&butler`: the work branch's remote (or "no git repo"); the topics and their builders (or "none yet"); `&main__qa` (or "none yet"); the next link after a push (or none); whether it may push.
- `&main__qa`: the check commands; what it may start.
- Deliverable builder: where the artefact goes.

## Follow-up brief

Send a follow-up for any later round on the same topic, and to standing agents across topics. Save it as `S/briefs/<name>-NN-<task>.md`, numbered on from the agent's last brief, and send it with `bb thread tell <id> --mode queue --message-file <brief>`. Agents are not replaced; the one exception is in [SKILL.md](../SKILL.md), "Claims, permissions, failures".

```markdown
From the Lead. User: "<exact quote>".

Task: <one paragraph>. Expected state: <branch, HEAD, clean tree>; if different, stop and report.

<Steps, changed limits, proof.>

Final answer: <shape>.
```
