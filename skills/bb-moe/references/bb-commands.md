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

## Spawn an agent

Always `--project` and `--parent-self`; choose the environment by role. `--provider` and `--model` come from the tier map in `S/logs/lead-state.md` (SKILL.md, "Models"); the role's tier is in `brief-template.md`, "Roles".

```sh
# builder (&<topic>__build): its own new worktree from an exact commit
bb thread spawn --project "$BB_PROJECT_ID" --parent-self --title '&auth__build' \
  --provider <provider> --model <mid-tier model> --reasoning-level high \
  --new-environment worktree --base-branch <sha> \
  --prompt-file S/briefs/auth__build-01-<task>.md --json

# QA, reviewer, review-skeptic: the builder's environment (its environmentId).
# The reviewer and the review-skeptic run on the stronger tier.
bb thread spawn --project "$BB_PROJECT_ID" --parent-self --title '&auth__qa' \
  --provider <provider> --model <mid-tier model> --reasoning-level high \
  --environment <builder env id> \
  --prompt-file S/briefs/auth__qa-01-<task>.md --json

# debrief, architect, arch skeptic, scouts, &butler, &main__qa: your own environment
bb thread spawn --project "$BB_PROJECT_ID" --parent-self --title '&debrief__analyst' \
  --provider <provider> --model <stronger model> --reasoning-level high \
  --environment "$BB_ENVIRONMENT_ID" \
  --prompt-file S/briefs/debrief__analyst-01-<task>.md --json
```

- Without an environment flag, a child gets a fresh worktree of the project's default branch, not your branch.
- `--base-branch`: a SHA or explicit ref is used exactly. A branch name may resolve to the remote copy when the local one is not ahead. Give a SHA.
- The JSON answer carries `id` and `environmentId`: put both in the registry. `bb thread show <id> --json` gives them later.
- `--parent-notifications stuck` stops finished turns from waking you. Failures and blockers still wake you. The agent must then send its results with `bb thread tell`. Keep the default (`auto`) unless the wake-ups are noise.

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
