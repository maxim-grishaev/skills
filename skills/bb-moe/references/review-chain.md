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

- Blocking findings go to the builder in one message (`moe-agent.py tell <builder> <<'EOF'`). The fix goes through QA again, and QA's new pass comes to you. Re-check only those findings.
- Follow-up findings go to the Lead (`moe-agent.py tell-lead`).
- A pass on an uncommitted tree waits for the builder's `committed` message. Then check, in the shared worktree, that `git status` is clean and HEAD is that SHA.
- No blocking finding left: send the final pass (`--kind review-passed`).

## Message formats

Every message of the chain is sent with `moe-agent.py tell <name> --kind <kind> <flags>`. The wording lives in a template file under `templates/` in the skill's folder, next to `scripts/`; the script fills it from the flags, checks each commit with `git rev-parse` in your worktree, sends it in full, and sends nothing when a flag is missing. `moe-agent.py tell --help` lists the kinds and their flags. `--topic` defaults to the topic of your own name; `--builder` to the registered `&<topic>__build`.

| Kind | From, to | Flags | Template |
|---|---|---|---|
| `ready-for-qa` | builder, QA | `--summary`, plus `--commit` once commits are allowed | `chain/ready-for-qa.md`, `chain/ready-for-qa-commit.md` |
| `qa-passed` | QA, the reviewer (later fixes: the last gate) | `--commit <SHA>` or `working-tree`, `--branch`, `--base` | `chain/qa-passed.md` |
| `review-findings` | reviewer, review-skeptic | `--review NN` (the report `S/reports/<topic>__review-NN.md`, which must exist), plus the flags of `qa-passed` | `chain/review-findings.md` |
| `committed` | builder, the last gate | `--commit`, `--branch` | `chain/committed.md` |
| `review-passed` | last gate, `&butler` (landing allowed) or `lead` | `--commit`, `--branch`, `--base` | `chain/review-passed.md` |
| `merged` | `&butler`, `&main__qa` | `--commit` | `chain/merged.md` |
| `main-qa-passed` | `&main__qa`, `&butler` | `--commit` | `chain/main-qa-passed.md` |
| `main-qa-failed` | `&main__qa`, `&butler` and the builder (two calls) | `--commit`; the defects, in the QA defect shape, on stdin | `chain/main-qa-failed.md` |
| `pushed` | `&butler`, the next link | `--commit` (the full SHA) | `chain/pushed.md` |
| `need-main-qa` | `&butler`, `lead` (no `&main__qa` registered) | `--commit` | `lead/need-main-qa.md` |

Every message that names a commit also names the topic, the branch and the base, so a later link can diff and send a failure back.

## Rules for every link

- A script that refuses (missing flag, unknown commit, no such report) sent nothing. Fix the call. A `NOT delivered` or `UNCONFIRMED` answer is for the Lead: the first means bb refused twice; the second means bb answered without `sent` or `queued`, the message may have arrived, and the script did not resend it.
- Act only on the message your brief names as your trigger. It arrives in your brief at spawn, or by message in later rounds.
- The next link is not in the registry yet? Send your hand-off as usual, to its name. The script sends it to the Lead instead (`lead/handoff-unspawned.md`, with your message inside) and prints the line to end your turn with: `waiting for Lead on &<next link>`. The Lead spawns the next link with your message as its trigger.
- A fail or an unclear message: stop and report. Never guess.
- Several expected messages: handle whichever comes first, one at a time.
