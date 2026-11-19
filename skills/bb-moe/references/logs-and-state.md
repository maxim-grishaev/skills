# Logs, state snapshot, storage

Everything lives under your storage root `S`: the absolute path of the Lead's `$BB_THREAD_STORAGE`. Each agent has its own `$BB_THREAD_STORAGE`, so agents write to `S` by absolute path.

Agents keep their logs by `roles/common.md`, "Log and report".

```
S/
  briefs/     <name>-NN-<task>.md: every brief and follow-up, as sent
  logs/       lead-state.md and team.json (always); lead.md and <name>.md per agent (name without `&`)
  reports/    debrief.md, long reports (<name>-NN.md), the running findings file
  design/     architecture.md, roadmap.md (written by &architect); adr/NNNN-<slug>.md
  evidence/   <name>/: screenshots, captures, command output
  secrets/    dotenv files written by `bb secret request` (delete when done)
```

Delete large artefacts (builds, unpacked bundles, copies) once they are superseded. Keep logs, briefs and reports.

## Lead timeline: `logs/lead.md`

```markdown
# Lead log: <work>

Thread: <id>   Project: <id>   Environment: <id>   Worktree: <path>
Sources: <ticket, design doc, copies in S>

## Standing rules (from the user)

- <rule> (user, <date>)
- <the Lead's added limit> (Lead)

## Timeline

- <timestamp> user: "<request, short quote>". <What you dispatched: agent, brief file.>
- <timestamp> &<name> done: <result in one or two lines, marked seen/inferred, on what>. <Next step.>
- <timestamp> DECISION (user | Lead): <what>.
- <timestamp> CORRECTION: <what was wrong, who found it, what changes>.
```

Append only; mark who decided each decision.

## Team file: `logs/team.json`

The machine-readable state that `moe.py` reads and writes; edit it only through `moe.py`. `setup` writes `lead` (your thread, project, environment, worktree, branch), `tiers` (provider, stronger, mid) and `weight`. `brief --spawn` adds one entry per agent under `agents`: thread, environment, role, model, task, brief path, spawn time. This is the team registry: agents look up thread IDs there.

## State snapshot: `logs/lead-state.md`

Rewrite it whole whenever the state changes in a way that matters, and always before a compaction or a long pause. Together with `logs/team.json`, it must be enough to continue the work with nothing else in context.

```markdown
# Lead state snapshot (written <timestamp>)

Read this first after a compaction or hand-off, then `logs/team.json`. Full history: `logs/lead.md`.

## Who I am and how I work here

- Lead of <work>. My thread, project, environment, worktree and the weight are in `logs/team.json`.
- Storage root: <S>. Weight set by the Lead after the debrief on <date>. Later changes: <approved by the user on <date>: <reason> / none>.
- Model tiers in `logs/team.json`, mapped on <date> by <the Lead / the user>. Overruled by the user: <what, date / no>.
- Landing allowed for: <no topic / all topics / named topics>. Commits allowed: <yes / no>.
- How the user wants replies: <style>.

## Standing rules from the user

- <rule>

## Code state

- Branch <b>: HEAD <sha>, pushed or not, what it contains, check state, CI state.
- Stale branches not to merge (old base): <list>. Backup refs: <ref = sha>.
- Facts worth keeping that cost effort to find: <list>.

## Running because of us

| What | Where (terminal, port, URL) | Owner | How to stop |
|---|---|---|---|

## Agents' state

IDs, environments and models are in `logs/team.json`.

| Name | State (idle / waiting for &x on … / done) |
|---|---|

## Design and roadmap

- Design: `S/design/architecture.md`, approved by the user <date> (or open: <what>).
- Roadmap: task -> state (done, commit / in progress, agents / not started).

## Current task

- The user's request and decisions, quoted.
- Chain in flight: who waits for whom, on what.

## Decisions

- <decision> (user | Lead, <date>).

## Waiting on the user

1. <question or action, with your recommendation>
```

## Findings file: `reports/<work>-findings.md`

For results the user wants later, for a write-up or a decision record. One numbered entry per finding; numbers continue across sections:

```markdown
### F<n>. <one-line finding> (<date>)

- **What:** <fact, with file paths or commands>
- **Evidence:** <who checked, on what, seen or inferred>
- **What it means:** <consequence>
- **Options / decision:** <choices; the user's decision quoted if made>
```

Several agents may append at once: by `roles/common.md`, "Log and report", re-read right before you write and never rewrite other entries.
