# The review chain

For the agents in a topic's review chain: builder, QA, reviewer, review-skeptic, `&butler`, `&main__qa` and the deliverable builder. Terms (topic, landing, last gate, `S`, `R`): `R/roles/common.md`. This file is `R/review-chain.md`.

## The chain

The review chain runs whether or not landing is allowed:

1. QA passes.
2. The reviewer reviews.
3. The review-skeptic passes. In a light job there is none: the reviewer's pass is the final pass.

Until commits are allowed, QA tests the builder's working tree. The last gate sends the final pass to the Lead until landing is allowed, and to `&butler` after that, always naming a commit.

## The last gate

If you are the last gate:

- Blocking findings go to the builder in one message. The fix goes through QA again, and QA's new pass comes to you. Re-check only those findings.
- Follow-up findings go to the Lead.
- A pass on an uncommitted tree waits for the builder's "committed tested tree as <SHA>". Then check, in the shared worktree, that `git status` is clean and HEAD is that SHA.
- No blocking finding left: send the final pass.

## Message formats

- Builder to QA: "<topic> ready for QA: <what changed>", plus "commit <SHA>" once commits are allowed.
- QA to reviewer: "<topic> QA PASSED, commit <full SHA or 'working tree'> on branch <X>, base <SHA>, builder &<topic>__build (<id>)".
- Reviewer to review-skeptic: "<topic> findings: S/reports/<topic>__review-NN.md", plus the fields of QA's message.
- Builder to the last gate: "<topic> committed tested tree as <SHA> on branch <X>".
- Last gate to `&butler` (landing allowed) or to the Lead: "<topic> review PASSED, commit <SHA> on branch <X>, base <SHA>, builder &<topic>__build (<id>)".
- `&butler` to `&main__qa`: "merged <SHA>". The answer is "main QA PASSED <SHA>", or "main QA FAILED <SHA>" with the defects in the QA defect shape (also sent to the builder).
- `&butler` to the next link: "pushed <full SHA>".

## Rules for every link

- Every chain message carries the commit, its base commit and the builder's thread ID. Any later link can then diff and send a failure back.
- Act only on the message your brief names as your trigger. It arrives in your brief at spawn, or by message in later rounds.
- The next link is not in the registry yet? End your turn with your hand-off message, with all its fields, then `waiting for Lead on <next link>`. The Lead spawns the next link with it.
- A fail or an unclear message: stop and report. Never guess.
- Several expected messages: handle whichever comes first, one at a time.
