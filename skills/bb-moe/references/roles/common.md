# Team rules: every role

These rules apply to every agent the Lead dispatches. Your brief gives the task. This file and your role file (`R/roles/<role>.md`) say how the team works. If your brief and these files differ, the brief wins. What the user tells you in your own thread wins over both.

## Terms

- `S` is the storage root your brief names (absolute). `R` is the skill's `references/` directory (absolute); this file is `R/roles/common.md`.
- A **topic** is the piece of work that one group of agents shares. It is the first part of their names: `&auth__build` and `&auth__qa` work on topic `auth`.
- The **work branch** is the Lead's branch. Each topic is built on its own branch; `&butler` merges it into the work branch.
- **Landing** a topic means merging it into the work branch and pushing. It happens only once the user allows it.
- The job's **weight** is in your brief: full or light. A light job has no architect, no arch skeptic's check and no review-skeptic. A job is light only when all of these hold:
  - one topic;
  - no open design decision: every design choice has one clear answer;
  - the change stays inside one workspace: one package or app, nothing built or deployed separately.

  In a light job, anything that breaks one of these conditions is a scope change. Stop that part and tell the Lead.
- The **review chain** takes a topic from QA's pass to its final pass; its rules and messages are in `R/review-chain.md`. The **last gate** is the agent whose pass ends it: the review-skeptic in a full job, the reviewer in a light one.

## Who decides

- You may ask the user in your own thread and stop until they answer. Ask by `R/ask-user.md`. Write down what you have first, so a late answer loses nothing. Your role file may narrow this: a scout never asks the user; it reports to the agent it works for.
- Anything that changes scope, the design, the weight, landing or a user decision goes to the Lead. If the user told you such a thing in your thread, tell the Lead what the user said, quoted.

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
