# Logs, state snapshot, storage

Everything lives under your storage root `S`: the absolute path of the Lead's `$BB_THREAD_STORAGE`. Each agent has its own `$BB_THREAD_STORAGE`, so agents write to `S` by absolute path.

Format and rules: `roles/common.md`, "Log and report". Agents append as they go. The next fresh agent reads the log instead of rediscovering a recipe.

```
S/
  briefs/     <name>-NN-<task>.md: every brief and follow-up, as sent
  logs/       lead-state.md (always); lead.md and <name>.md per agent (name without `&`)
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

## State snapshot: `logs/lead-state.md`

Always kept. Rewrite it whole whenever the state changes in a way that matters, and always before a compaction or a long pause. It must be enough to continue the work with nothing else in context. It holds the team registry agents look up thread IDs in.

```markdown
# Lead state snapshot (written <timestamp>)

Read this first after a compaction or hand-off. Full history: `logs/lead.md`.

## Who I am and how I work here

- Lead of <work>: thread <id>, project <id>, environment <id>, worktree <path>.
- Storage root: <S>. Weight: <full (default) / light, approved by the user on <date>>.
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

## Team registry

| Name | Thread | Environment | Task | Model | State (idle / waiting for &x on … / done) |
|---|---|---|---|---|---|

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

## ADRs: `design/adr/NNNN-<slug>.md`

An ADR records one decision. Write one only when at least one holds:

- The decision is hard to reverse.
- It crosses topics, so several agents build on it.
- The user chose between real alternatives.

Not for every choice. A light job has none: a decision that needs one makes the job full. `&architect` writes most ADRs; whoever makes such a decision later writes its ADR. Number ADRs in order: `0001-<slug>.md`. If the project keeps its own ADRs, follow its format; write into the repo only if the user allowed it.

```markdown
# <NNNN>. <decision in one line> (<date>)

Status: <proposed / accepted by <the user or the Lead> / superseded by NNNN>

## Context
<What forces the decision. Facts, marked seen or inferred.>

## Decision
<What we do.>

## Options rejected
- <option>: <why not>

## Consequences
<What gets easier, what gets harder, what to watch.>
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

Several agents may append at once. Re-read the file right before you write, and append your own section. Never rewrite other entries.
