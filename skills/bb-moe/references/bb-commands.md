# bb commands for the Lead

Checked against `bb guide` and `--help`. For anything not here: `bb guide threads`, `bb guide thread-messaging`, `bb guide thread-inspection`, `bb guide thread-lifecycle`, or `bb <command> --help`. `S` stands for your storage root, written out as an absolute path. Pass long text with `--prompt-file` / `--message-file`: inside double quotes the shell runs backticks and `$(...)` before bb sees them.

## Context

```sh
bb thread update --self --title '<emoji> Lead (<task summary>)'   # e.g. '🧾 Lead (CSV export)'
bb status                          # project, thread, parent, environment
echo "$BB_THREAD_STORAGE"          # your storage root S (each child has its own)
bb thread show "$BB_THREAD_ID" --json   # thread.providerId: your own provider
bb settings show --json                 # generalSettings.defaultProviderId: the user's default provider
bb provider list --json                 # providers, with `available`
bb provider models <provider> --project "$BB_PROJECT_ID" --json   # its models, for the tier map (SKILL.md, setup step 6)
bb thread context --self --json    # how full your context is
```

## Record the tier map and the weight

`M` stands for `python3 <this skill's directory>/scripts/moe-lead.py`.

```sh
M setup --provider <id> --stronger <model id> --mid <model id>   # setup step 6; writes S/logs/team.json
M setup --weight light                                            # after the debrief
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

- Names go without `&`; the script adds it. The body comes only from stdin, through a quoted heredoc: the shell expands nothing inside `<<'EOF'`.
- The script runs `bb thread spawn --project --parent-self` with the role's environment, the tier's `--provider` and `--model`, `--reasoning-level high` and `--parent-notifications stuck`. A builder's `--base-branch` is your worktree's HEAD as a SHA. It adds the agent's `id` and `environmentId` to `S/logs/team.json`.
- Without `--spawn` it saves the brief and prints the `bb thread spawn` command it would run.
- `M brief --help` lists every flag and its default.

## Talk to an agent

```sh
bb thread tell <id> --message-file S/briefs/<name>-NN-<task>.md              # steers the active turn (default)
bb thread tell <id> --mode queue --message-file S/briefs/<name>-NN-<task>.md # waits until the agent is free
```

A send reported as `queued` is not a failure; do not resend. Agents use the same command to talk to each other.

## Read an agent

```sh
bb thread output <id>              # full final answer (notifications are truncated)
bb thread show <id> --json         # status, environment, errors
bb thread log <id>                 # event log; --all for everything
bb thread wait <id> --timeout 20m  # block until idle; only when your next step needs it
```

In chat, link an agent as `@thread:<id>`; never build thread URLs by hand.

## Recover and clean up

```sh
bb thread retry <id>               # retry a failed turn (after a spend limit or outage)
bb thread compact <id>             # only on an idle or errored thread; not on yourself mid-turn
bb thread stop <id>                # stop its work and release the runtime
```

Archiving or deleting agent threads and their worktrees is the user's call.

## Credentials, servers, sharing

```sh
bb secret request TEST_EMAIL TEST_PASSWORD --write-env S/secrets/test-login.env \
  --purpose 'Sign-in for the QA agent on the staging environment'
# values go from the user's form into the file (mode 0600); they never appear in the transcript

bb terminal create --thread <id> --command '<long-running command>'   # a server that outlives one command
bb terminal list --thread <id>
bb connect expose <port>           # share a local HTTP port through the user's bb address (owner session only)
bb connect unexpose <port>
```
