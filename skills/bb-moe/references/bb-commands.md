# Commands for the Lead

Every bb call the skill teaches goes through a script verb. `M` stands for `python3 <this skill's directory>/scripts/moe-lead.py`; `M --help` and `M <verb> --help` list every flag and default. `S` stands for your storage root, written out as an absolute path. Run each call as one plain command, never chained with `;`, `&&` or `|`. Pass long text on stdin through a quoted heredoc (`<<'EOF'`): inside double quotes the shell runs backticks and `$(...)` before the script sees them. Agents use `moe-agent.py`; its verbs are in [roles/common.md](roles/common.md).

Names go without `&`; the script adds it.

## Set up

```sh
M setup --title '<emoji> <task summary>'                           # SKILL.md, setup step 1; needs no team.json
M models                                                           # the provider and its models, for the tier map (step 6)
M setup --provider <id> --stronger <model id> --mid <model id>     # step 6; writes S/logs/team.json
M setup --weight light                                             # after the debrief
```

## Spawn an agent

```sh
M brief --name auth__build --role build --task 'OAuth sign-in' \
  --commit no --push no --start 'dev server on port 3000' \
  --peers auth__qa,butler --spawn <<'EOF'
## The user's request, word for word

"<exact quote>"

## Your task
...
EOF
```

- The body comes only from stdin. The shell expands nothing inside `<<'EOF'`.
- The script spawns the agent with the role's environment, the tier's provider and model, `--reasoning-level high` and `--parent-notifications stuck`. A builder's base is your worktree's HEAD as a SHA. It registers the agent in `S/logs/team.json` right after the spawn.
- Without `--spawn` it saves the brief and prints the spawn command it would run.
- `--permission-mode accept-edits|auto|full` is for a test or a user who wants one agent in another mode; the default is your own mode.

## Talk to an agent

```sh
M follow-up --name auth__build --task 'fix round 1' <<'EOF'   # a later brief: saved as S/briefs/<name>-NN-<task>.md, sent queued
M tell auth__qa <<'EOF'                                       # a short message, at most 8 lines or 1200 characters
M tell butler --kind compact-the-lead                         # a fixed message: the files in templates/from-lead/
```

`--now` on `follow-up` and `tell` steers the agent's current turn instead of queueing: only to interrupt it. A send reported as `queued` is not a failure; do not resend. A refused send exits 1 with "NOT delivered".

## Read an agent

```sh
M status                  # every agent: bb status, its last message, a flag for an idle agent that has sent nothing since spawn or your last message; child threads not in the registry; your context use
M status auth__build      # one agent
M show auth__build        # status, provider, environment
M output auth__build      # its full final answer (notifications are truncated)
M log auth__build         # its event log; --all for everything
M wait auth__build        # block until idle (--timeout 20m); only when your next step needs it. Exit 0 idle, 2 timeout, 4 errored
```

`wait` waits 20 minutes by default. Pass a `--timeout` shorter than your shell's command limit, or the shell may kill the call first; exit 2 then means "timed out", not "refused".

In chat, link an agent as `@thread:<id>`; never build thread URLs by hand. The IDs are in `S/logs/team.json`.

## Wait on the user

```sh
M wait-user 'Q2 - model tier'             # ❓ in your title, one notification, prints the line to end on
M wait-user --act 'sign in to staging'    # ❗️: the user must do something that is not an answer
M user-answered                           # nothing stays open: take the marker off
```

Rules: [ask-user.md](ask-user.md).

## Recover and clean up

```sh
M retry auth__build       # retry a failed turn; refuses the 4th time until the agent reports again
M compact auth__build     # only an idle or errored agent
M stop auth__build        # stop its work and release the runtime
```

Archiving or deleting agent threads and their worktrees is the user's call.

## Raw bb extras

These stay raw: they are rare, interactive or infrastructure, with no team rule to enforce (ADR 0001).

```sh
bb secret request TEST_EMAIL TEST_PASSWORD --write-env S/secrets/test-login.env \
  --purpose 'Sign-in for the QA agent on the staging environment'
# values go from the user's form into the file (mode 0600); they never appear in the transcript

bb terminal create --thread <id> --command '<long-running command>'   # a server that outlives one command
bb terminal list --thread <id>
bb connect expose <port>           # share a local HTTP port through the user's bb address (owner session only)
bb connect unexpose <port>
bb guide                           # bb's own docs; `bb <command> --help` for one command
```
