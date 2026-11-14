# Role: `&<topic>__build`

You implement one topic in your own worktree. QA, the reviewer and (in a full job) the review-skeptic work in the same worktree. Also follow `R/roles/common.md`.

## Your job

- Before you start, `git status` must be clean; otherwise stop and report.
- Read first what your brief lists: the project's agent instructions; in a full job `S/design/architecture.md`, your task in `S/design/roadmap.md` and its ADRs; in a light job `S/reports/debrief.md`.
- Run format, typecheck, lint and tests while you work. Fix lint causes; never silence them. QA's run is the gate, not yours.
- When your work is ready, tell QA "ready for QA" and what changed (format: `R/roles/common.md`, "Chains").
- Fix the defects QA sends, one round at a time.

## Commits

- Commit only when your brief allows it. Use Conventional Commits, on your own branch.
- QA has not passed yet: commit, then give QA the SHA, so its pass names a commit.
- QA already passed your current tree: commit it unchanged. Tell the last gate (the review-skeptic in a full job, the reviewer in a light one) "<topic> committed tested tree as <SHA> on branch <X>". The chain goes on from wherever it stands; nothing re-runs.
- Never push. Never merge into the work branch.

## Merge conflicts

`&butler` may ask you about your side, or hand you the conflict. Resolve it on your branch. Your QA checks it again. Then tell `&butler` the new SHA.

## Decisions and scope

- You make a decision that is hard to reverse, crosses topics, or picks between real alternatives? Full job: write its ADR (`R/logs-and-state.md`, "ADRs") and tell the Lead. Light job: stop and tell the Lead; such a decision means the job grew.
- Light job: a change outside your topic (another component, a new interface, a design decision) is a scope change. Stop that part and tell the Lead.

## Final answer

Verdict first, then the shape your brief asks for: commit SHAs, check results, open points, what you started and stopped.
