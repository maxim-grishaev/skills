#!/usr/bin/env python3
"""Dispatch helper for the bb-moe Lead.

`setup` records the Lead's IDs, the model tier map and the weight in
S/logs/team.json. `brief` renders an agent's brief from flags plus a Markdown
body on stdin and templates/brief/, saves it as S/briefs/<name>-NN-<task>.md and,
with --spawn, spawns the agent and adds it to the team registry in S/logs/team.json.

S is the Lead's storage root ($BB_THREAD_STORAGE). Run it from the Lead's
thread; every verb except the first `setup` refuses from any other thread.
Agents use moe-agent.py. Python 3 standard library only.
"""

import argparse
import os
import sys
import time

from moelib import brief as brieflib
from moelib import team as teamlib
from moelib.runtime import BbError, BbRuntime
from moelib.templates import TemplateError
from moelib.util import Failure, die, now, read_stdin_body, shell_quote

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
AGENT_CLI = "python3 " + shell_quote(os.path.join(SCRIPTS, "moe-agent.py"))

EPILOG = """\
examples:
  moe-lead.py setup --provider claude-code --stronger claude-opus-5-5 --mid claude-sonnet-5-5
  moe-lead.py setup --weight light

  moe-lead.py brief --name auth__build --role build --task 'OAuth sign-in' \\
    --commit no --push no --start 'dev server on port 3000' \\
    --peers auth__qa,butler --spawn <<'EOF'
  ## The user's request, word for word
  "<exact quote>"
  ...
  EOF

The body comes only from stdin, through a quoted heredoc (<<'EOF'): inside
double quotes the shell runs backticks and $(...) before the script sees them.
"""


# ---------------------------------------------------------------- setup


def cmd_setup(args, rt):
    me = rt.whoami()
    root = me.get("storage")
    if not root:
        raise Failure("no storage root: run this from the Lead's bb thread", header="error: nothing written")
    team = teamlib.load_team(root) or {}
    errors = []
    first = "lead" not in team

    if first:
        thread = me.get("thread")
        if not thread:
            errors.append("this thread's ID is unknown: run this from the Lead's bb thread")
        else:
            try:
                shown = rt.show(thread)
            except BbError as e:
                errors.append("showing thread %s failed: %s" % (thread, e))
            else:
                env = shown["environment"] or {}
                team["lead"] = {
                    "thread": thread,
                    "project": shown["project"],
                    "environment": shown["environment_id"],
                    "worktree": env.get("path"),
                    "branch": env.get("branch"),
                    "isGitRepo": bool(env.get("is_git_repo")),
                }
        missing = [f for f in ("provider", "stronger", "mid") if not getattr(args, f)]
        if missing:
            errors.append("first setup needs --%s" % ", --".join(missing))
    else:
        teamlib.require_lead(team, me, root)

    if errors:
        raise Failure(errors, header="error: nothing written or spawned")

    tiers = team.setdefault("tiers", {})
    for field in ("provider", "stronger", "mid"):
        if getattr(args, field):
            tiers[field] = getattr(args, field)
    if args.weight:
        team["weight"] = args.weight
    team.setdefault("agents", {})
    teamlib.save_team(root, team)
    print("wrote %s" % teamlib.team_path(root))
    print("tiers: provider %s, stronger %s, mid %s; weight: %s"
          % (tiers.get("provider"), tiers.get("stronger"), tiers.get("mid"),
             team.get("weight", "not set")))
    return 0


# ---------------------------------------------------------------- brief


def spawned_environment(rt, spawned, tries=3):
    """The new thread's environment ID. A spawn into a new worktree may print none, so ask bb
    for the thread (a few tries: the environment can appear a moment later). None if still unknown."""
    if spawned["environment"]:
        return spawned["environment"]
    for attempt in range(tries):
        try:
            shown = rt.show(spawned["thread"])
        except BbError:
            shown = {}
        env = shown.get("environment_id")
        if env:
            return env
        if attempt < tries - 1:
            time.sleep(1.0)
    return None


def cmd_brief(args, rt):
    me = rt.whoami()
    root = me.get("storage")
    if not root:
        raise Failure("no storage root: run this from the Lead's bb thread")
    team = teamlib.load_team(root)
    if team is None:
        raise Failure("no %s: run `moe-lead.py setup` first (SKILL.md, setup step 6)" % teamlib.team_path(root))
    teamlib.require_lead(team, me, root)

    errors = []
    try:
        body = read_stdin_body()
    except Failure as f:
        errors += f.errors
        body = ""
    plan = None
    try:
        plan = brieflib.prepare(args, rt, root, team, me, body, AGENT_CLI)
    except Failure as f:
        errors = f.errors + errors
    if errors:
        raise Failure(errors, header="error: nothing written or spawned")

    path = brieflib.save(root, plan)
    plan["spec"]["prompt_file"] = path
    print("brief: %s" % path)
    if not args.spawn:
        print("dry run, nothing spawned. Spawn with the same flags plus --spawn, or run:")
        print("  " + rt.describe_spawn(plan["spec"]))
        return 0

    name = plan["name"]
    try:
        spawned = rt.spawn(plan["spec"])
    except BbError as e:
        raise Failure("spawn failed; the brief is saved, nothing registered:\n%s" % e, exit_code=1)
    if not spawned["thread"]:
        # bb exited 0, so the agent may exist: never claim nothing was spawned
        raise Failure("spawned, but not registered: bb printed no thread ID. Check this thread's child "
                      "threads in bb before you spawn again. The brief is %s. bb printed:\n%s"
                      % (path, spawned["raw"].strip()), exit_code=1)
    environment = spawned_environment(rt, spawned)
    entry = {
        "thread": spawned["thread"],
        "environment": environment,
        "role": plan["role"],
        "model": plan["model"],
        "task": plan["task"],
        "brief": path,
        "spawned": now(),
    }
    if plan["spec"].get("permission_mode"):
        entry["permissionMode"] = plan["spec"]["permission_mode"]
    if plan["works_for"]:
        entry["worksFor"] = plan["works_for"]
    if plan["replaces"]:
        entry["replaces"] = plan["replaces"]
    team = teamlib.load_team(root)  # re-read right before the write
    team.setdefault("agents", {})[name] = entry
    teamlib.save_team(root, team)
    print("spawned &%s: thread %s, environment %s, model %s; registered in %s"
          % (name, spawned["thread"], environment, plan["model"], teamlib.team_path(root)))
    if not environment:
        print("warning: bb gave no environment ID for &%s, so `--env of:%s` will not work until it is "
              "added to %s" % (name, name, teamlib.team_path(root)), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- main


def build_parser():
    doc = __doc__.split("\n\n")
    parser = argparse.ArgumentParser(
        prog="moe-lead.py", description=doc[0] + "\n\n" + doc[1],
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="record the Lead's IDs, the tier map and the weight",
                       description="Create or update S/logs/team.json. The first run records the "
                                   "Lead's thread, project, environment and worktree from bb, and "
                                   "needs --provider, --stronger and --mid. Later runs change only "
                                   "the fields given, and only from the Lead's thread.")
    s.add_argument("--provider", help="provider ID for every spawn")
    s.add_argument("--stronger", metavar="MODEL", help="model ID of the stronger tier")
    s.add_argument("--mid", metavar="MODEL", help="model ID of the mid tier")
    s.add_argument("--weight", choices=brieflib.WEIGHTS, help="the job's weight, once set after the debrief")
    s.set_defaults(func=cmd_setup)

    b = sub.add_parser(
        "brief", help="render and save a brief; with --spawn, spawn and register the agent",
        description="Render a brief from templates/brief/: an opening, the Markdown body from stdin, "
                    "then Where you work, Limits and Team. Save it as S/briefs/<name>-NN-<task>.md. "
                    "Without --spawn it is a dry run: it saves the brief and prints the spawn command. "
                    "With --spawn it spawns the agent with --parent-notifications stuck and registers it "
                    "in S/logs/team.json. Every bad flag is reported at once, and then nothing is "
                    "written or spawned. Tier and environment default by role.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    b.add_argument("--name", help="agent name without '&', e.g. auth__build, butler")
    b.add_argument("--role", help="one of: %s; custom has no role file" % ", ".join(brieflib.ROLES))
    b.add_argument("--task",
                   help="the piece of work, one line; also the brief's file name and the registry's task")
    b.add_argument("--tier", help="stronger or mid; default by role")
    b.add_argument("--env", help="lead (the Lead's worktree), new-worktree (from the Lead's HEAD or "
                                 "--base), or of:<agent> (that agent's environment); default by role: "
                                 "qa, reviewer and review-skeptic join of:<topic>__build")
    b.add_argument("--base", metavar="REF", help="commit for --env new-worktree; default the Lead's HEAD")
    b.add_argument("--commit", default="no", help="yes or no: may commit on its branch (default no)")
    b.add_argument("--push", default="no", help="yes or no: may push; &butler only (default no)")
    b.add_argument("--start", metavar="TEXT", help="what it may start, e.g. 'dev server on port 3000'; default nothing")
    b.add_argument("--creds", metavar="FILE", help="the one credentials file it may read")
    b.add_argument("--peers", metavar="A,B", help="agents it talks to, comma-separated, without '&'")
    b.add_argument("--works-for", metavar="AGENT", help="scouts: the agent it works for")
    b.add_argument("--what", metavar="TEXT", help="role in one line; required for --role custom")
    b.add_argument("--title", help="thread title; default &<name>")
    b.add_argument("--permission-mode", choices=brieflib.PERMISSION_MODES, metavar="MODE",
                   help="accept-edits, auto or full, passed to bb as is; default none: the agent "
                        "inherits this thread's mode")
    b.add_argument("--replace", action="store_true",
                   help="spawn under a registered name: only for a crashed thread the user allowed to replace")
    b.add_argument("--spawn", action="store_true", help="spawn and register; without it, a dry run")
    b.set_defaults(func=cmd_brief)
    return parser


def main(argv=None, runtime=None):
    args = build_parser().parse_args(argv)
    rt = runtime or BbRuntime()
    try:
        return args.func(args, rt)
    except Failure as f:
        die(f)
    except BbError as e:
        print("error: bb: %s" % e, file=sys.stderr)
        return 1
    except TemplateError as e:
        print("error: nothing written or spawned\n  - template: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
