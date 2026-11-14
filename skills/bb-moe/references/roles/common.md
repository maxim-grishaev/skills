# Team rules: every role

These rules apply to every agent the Lead dispatches. Your brief gives the task. This file and your role file (`R/roles/<role>.md`) say how the team works. If your brief and these files differ, the brief wins. If the user says otherwise, the user wins.

`S` is the storage root your brief names (absolute). `R` is the skill's `references/` directory (absolute); this file is `R/roles/common.md`.

## Who decides

- What the user tells you in your own thread overrides your brief.
- You may ask the user in your own thread and stop until they answer. Write down what you have first, so a late answer loses nothing.
- Anything that changes scope, the design or a user decision goes to the Lead.
- The user told you something in your thread that changes scope, the weight, landing or the design? Tell the Lead what the user said, quoted.

## Talking to other agents

- Talk to any agent directly when the work needs it. The Lead is not a relay.
- Send with `bb thread tell <id> --mode queue --message-file - <<'EOF'`, then the text, then `EOF`. Drop `--mode queue` only to interrupt the other agent's current turn.
- Thread IDs are in the team registry in `S/logs/lead-state.md`. Only the Lead writes it. The Lead's own thread is your parent in `bb status`. Message it like any agent; in a waiting line, call it `Lead`.
- Send one message per round, with everything from that round. Send no thanks or acknowledgements.
- If your turn ends only because you wait, end it with one line: `waiting for &<name> on <what>`.
- Keep the full report for when your job is done. A final answer with a verdict tells the Lead you are done. Questions or a `waiting for` line tell it you are not.

## Claims

- Every claim says who checked it, on what (build, commit, device, environment), and whether it was seen or inferred. Keep the marking when you relay someone else's claim.
- Before you state a diagnosis as fact, run the cheapest check that tells it apart from the next likely cause.
- Something the user believes ("I think X is unused") is a hypothesis. Prove it from evidence before you act on it.
- Every artefact (build, export, report) says what it was built from: the commit, and a clean or dirty tree.

## Permissions

- Commit, push and start only what your brief allows.
- Infrastructure the user did not allow (servers, containers, emulators) is a blocker. Report it, do not start it, and carry on with the rest.
- Read credentials only from the file your brief names. Never put them in a file name, log or report.
- A sign-in is refused: try once more at most, then stop and report.
- A sandbox failure (network, install, device tools): retry that one command unsandboxed.
- A permission is refused: stop that path and report the exact command. Never work around it.
- Stop every process you started, and say so. If one must keep running, such as a server the user needs, put it in your report with how to stop it.
- Use absolute paths in every command. A `cd` that persists drifts your working directory. Never run a bare `git stash`.

## Log and report

- Keep `S/logs/<name>.md` (name without `&`). Start it with a heading that gives your thread ID (`$BB_THREAD_ID`). Add timestamped entries (`date -u +%FT%TZ`) as you go, not at the end.
- Log what you looked at, found and decided; dead ends; every refusal with the exact command; every message sent and received. The next agent reads your log instead of rediscovering your recipe.
- Put evidence in `S/evidence/<name>/` and long reports in `S/reports/<name>-NN.md`.
- Shared files, such as a findings file: re-read right before you write. Append your own section. Never rewrite other agents' sections.
- Your final answer starts with the verdict, because long answers reach the Lead cut short. Then give the shape your brief asks for.
- Write messages and final answers by `R/communication-style.md`: terse, payload verbatim, full sentences for questions and for anything saved to a file.

## Chains

The review chain runs whether or not landing is allowed:

1. QA passes.
2. The reviewer reviews.
3. The review-skeptic passes. In a light job there is none: the reviewer's pass is the final pass.

Before commits are allowed, QA tests the builder's working tree. The last gate sends the final pass: the review-skeptic in a full job, the reviewer in a light one (your brief says which). Before landing is allowed, the final pass goes to the Lead. Once landing is allowed, it goes to `&butler`, always naming a commit.

Message formats:

- Builder to QA: "<topic> ready for QA: <what changed>", plus "commit <SHA>" once commits are allowed.
- QA to reviewer: "<topic> QA PASSED, commit <full SHA or 'working tree'> on branch <X>, base <SHA>, builder &<topic>__build (<id>)". After any later fix (review, conflict, main QA), QA sends the new pass to the last gate instead.
- Reviewer to review-skeptic: "<topic> findings: S/reports/<topic>__review-NN.md", plus the fields of QA's message.
- Builder to the last gate: "<topic> committed tested tree as <SHA> on branch <X>".
- Last gate to `&butler` (landing allowed) or to the Lead: "<topic> review PASSED, commit <SHA> on branch <X>, base <SHA>, builder &<topic>__build (<id>)".
- `&butler` to `&main__qa`: "merged <SHA>". The answer is "main QA PASSED <SHA>", or "main QA FAILED <SHA>" with the defects in the QA defect shape (also sent to the builder).
- `&butler` to the next link: "pushed <full SHA>".

Rules for every link:

- Every chain message carries the commit, its base commit and the builder's thread ID. Any later link can then diff and send a failure back.
- Act only on the message your brief names as your trigger.
- A fail or an unclear message: stop and report. Never guess.
- Several expected messages: handle whichever comes first, one at a time.
