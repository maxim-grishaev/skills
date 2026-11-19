# Lessons

Each rule here came from something that went wrong, or nearly did, in real coordinated work. The case comes first, then the rule. Read this once at setup. Come back to the matching entry before you relay a result, state a diagnosis, merge, build a deliverable or retry a thread.

## Checks and gates

- **Checks that could not run.** A builder could not run the linter in its fresh worktree, because installs were missing. It said so only in its final report. The lint errors surfaced at merge.
   Rule: the brief makes the checks runnable: installs, one-time setup, exact commands. QA runs them as the gate, whatever the builder reported. `&main__qa` runs them on a merged tree when the work branch moved.

## Branches and merges

- **An old base drags history back.** The shared branch was rebased, but an agent's branch still sat on the old base. Merging it would have brought the old commits back.
   Rule: after a rebase, cherry-pick from stale branches, or start fresh from the new tip. Before every merge, `&butler` checks that the remote tip equals its local HEAD. It keeps a local backup ref before it rewrites history.

## Artefacts

- **A build from uncommitted code.** A build reached the user from a worktree with an uncommitted fix. Later the user wanted a build that matched the branch.
   Rule: every artefact says what it was built from: the commit, and a clean or dirty tree. A deliverable comes from an exact pushed commit with a clean tree. Its size and checksum are recorded.

## Threads and the harness

- **Dead threads that looked like bugs.** Several agent threads died at once. The cause was an account spend limit; another time, a provider outage.
   Rule: read a failed thread's own error before you react: `bb thread show <id> --json`, `bb thread log <id>`. Check whether it already resumed by itself. Once the limit or outage is over, run `bb thread retry <id>`. After 3 failed retries, the user decides.
- **Cut-short reports.** Long final answers arrive cut short in the parent's notification.
   Rule: agents send the Lead the verdict in about 5 lines and keep the rest in a report under `S/reports/`. Read the report, or `bb thread output <id>`, when a decision needs more.
- **A permission nobody could approve.** An in-process helper's push was refused, and the user had no thread to approve it in. The same push, run as a visible sub-thread, went through.
   Rule: delegated work runs in sub-threads. Report a refusal with the exact command; never work around it.
- **Directory drift.** The Lead's shell stayed in another directory after a `cd`. Later commands ran in the wrong place. An agent's failed in-place `sed` did the same.
   Rule: use absolute paths in every command.
- **The Lead's context filled up.** A state snapshot written beforehand made the compaction harmless.
   Rule: keep `lead-state.md` current. Write it before any compaction or long pause. The Lead cannot compact itself while its turn runs, because `bb thread compact` needs an idle thread; `&butler` compacts it once it is idle.

## Cost

- **Where the tokens went.** One session tree was measured:
   - The Lead ran on the most expensive model and used 48% of the cost. Its average context was about 240k tokens.
   - Calls above 200k context were 61% of the total.
   - An agent resumed more than an hour after its last call rewrites its whole context into the prompt cache. That was 19% of the total. Three of those resumes missed the hour by 5 to 12 minutes.
   - Sub-agents for small fetches, and one-line "waiting" turns, cost almost nothing.
   Rule: keep the Lead's context small. If a wait will end near the hour, check back before the hour. Compact an agent with a large context before a long idle.

- **Reuse topic agents.** Spawn a new agent only for a topic not handled before. Later rounds on a topic go to its existing agents. Compact a long agent and resume a stale one; do not replace either.

## Users and agents

- **Answers that came late.** An agent had to ask the user. It first wrote a version of its deliverable with the open points marked. Then it folded the answers in.
   Rule: write what you have before you stop to ask. Nothing is lost if the answer comes late, or never.
