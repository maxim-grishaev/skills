#!/usr/bin/env python3
"""Dispatch helper for the bb-moe Lead.

`setup` records the Lead's IDs, the model tier map and the weight in
S/logs/team.json. `brief` renders an agent's brief from flags plus a Markdown
body on stdin, saves it as S/briefs/<name>-NN-<task>.md and, with --spawn,
spawns the agent and adds it to the team registry in S/logs/team.json.

S is the Lead's storage root ($BB_THREAD_STORAGE). Run it from the Lead's
thread, where $BB_THREAD_ID, $BB_PROJECT_ID and $BB_THREAD_STORAGE are set.
Python 3 standard library only.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

REFERENCES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references"
)

# role: (role file, tier, environment, read-only, role in one line)
# Mirrors references/brief-template.md, "Roles".
ROLES = {
    "debrief": ("debrief.md", "stronger", "lead", True, "the debrief analyst"),
    "scout": ("scout.md", "mid", "lead", True, "the scout"),
    "architect": ("architect.md", "stronger", "lead", False, "the architect"),
    "arch-skeptic": ("arch-skeptic.md", "stronger", "lead", True, "the arch skeptic"),
    "build": ("build.md", "mid", "new-worktree", False, "the builder"),
    "qa": ("qa.md", "mid", "builder", False, "the QA gate"),
    "reviewer": ("reviewer.md", "stronger", "builder", True, "the reviewer"),
    "review-skeptic": ("review-skeptic.md", "stronger", "builder", True, "the review-skeptic"),
    "main-qa": ("main-qa.md", "mid", "lead", False, "the work branch's QA gate"),
    "butler": ("butler.md", "mid", "lead", False, "the Lead's scout and integrator"),
    "delivery": ("delivery.md", "mid", "new-worktree", False, "the deliverable builder"),
    "custom": (None, None, None, False, None),
}
TIERS = ("stronger", "mid")
WEIGHTS = ("full", "light")
NO_WEIGHT = "not set yet; the Lead sets it after the debrief"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(__[a-z0-9][a-z0-9-]*)?$")

EPILOG = """\
examples:
  moe.py setup --provider claude-code --stronger claude-opus-5-5 --mid claude-sonnet-5-5
  moe.py setup --weight light

  moe.py brief --name auth__build --role build --task 'OAuth sign-in' \\
    --commit no --push no --start 'dev server on port 3000' \\
    --peers auth__qa,butler --spawn <<'EOF'
  ## The user's request, word for word
  "<exact quote>"
  ...
  EOF

The body comes only from stdin, through a quoted heredoc (<<'EOF'): inside
double quotes the shell runs backticks and $(...) before the script sees them.
"""


class Failure(Exception):
    pass


def storage_root():
    root = os.environ.get("BB_THREAD_STORAGE")
    if not root:
        raise Failure("$BB_THREAD_STORAGE is not set: run this from the Lead's bb thread")
    return root


def team_path(root):
    return os.path.join(root, "logs", "team.json")


def load_team(root):
    path = team_path(root)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_team(root, team):
    path = team_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(team, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def run(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "", "command not found: " + cmd[0]
    return p.returncode, p.stdout, p.stderr


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- setup


def cmd_setup(args):
    root = storage_root()
    team = load_team(root) or {}
    errors = []
    first = "lead" not in team

    if first:
        thread = os.environ.get("BB_THREAD_ID")
        if not thread:
            errors.append("$BB_THREAD_ID is not set: run this from the Lead's bb thread")
        else:
            code, out, err = run(["bb", "thread", "show", thread, "--json"])
            if code != 0:
                errors.append("bb thread show %s failed: %s" % (thread, err.strip() or out.strip()))
            else:
                shown = json.loads(out)
                env = shown.get("environment") or {}
                team["lead"] = {
                    "thread": thread,
                    "project": shown["thread"]["projectId"],
                    "environment": shown["thread"]["environmentId"],
                    "worktree": env.get("path"),
                    "branch": env.get("branchName"),
                    "isGitRepo": bool(env.get("isGitRepo")),
                }
        missing = [f for f in ("provider", "stronger", "mid") if not getattr(args, f)]
        if missing:
            errors.append("first setup needs --%s" % ", --".join(missing))

    if errors:
        fail(errors)

    tiers = team.setdefault("tiers", {})
    for field in ("provider", "stronger", "mid"):
        if getattr(args, field):
            tiers[field] = getattr(args, field)
    if args.weight:
        team["weight"] = args.weight
    team.setdefault("agents", {})
    save_team(root, team)
    print("wrote %s" % team_path(root))
    print("tiers: provider %s, stronger %s, mid %s; weight: %s"
          % (tiers.get("provider"), tiers.get("stronger"), tiers.get("mid"),
             team.get("weight", "not set")))


# ---------------------------------------------------------------- brief


def slugify(text):
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return "-".join(words[:6])[:40].strip("-") or "task"


def resolve_commit(worktree, ref):
    code, out, err = run(["git", "-C", worktree, "rev-parse", "--verify", "--quiet", ref + "^{commit}"])
    if code != 0:
        return None
    return out.strip()


def environment_path(env_id):
    code, out, _ = run(["bb", "environment", "show", env_id, "--json"])
    if code != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    data = data.get("environment", data)
    return data.get("path")


def cmd_brief(args):
    errors = []
    for flag in ("name", "role", "task"):
        if not getattr(args, flag):
            errors.append("--%s is required" % flag)
    checks = (("role", list(ROLES)), ("tier", TIERS), ("commit", ("no", "yes")), ("push", ("no", "yes")))
    for flag, allowed in checks:
        value = getattr(args, flag)
        if value is not None and value not in allowed:
            errors.append("--%s %s: use one of %s" % (flag, value, ", ".join(allowed)))
            setattr(args, flag, None)
    args.name = args.name or ""
    args.task = args.task or ""

    try:
        root = storage_root()
    except Failure as e:
        fail([str(e)])
    team = load_team(root)
    if team is None:
        fail(errors + ["no %s: run `moe.py setup` first (SKILL.md, setup step 6)" % team_path(root)])
    lead = team.get("lead", {})
    tiers = team.get("tiers", {})
    agents = team.get("agents", {})

    # name
    name = args.name
    if name.startswith("&"):
        errors.append("--name %s: give the name without '&'; the script adds it" % name)
        name = name.lstrip("&")
    if name and not NAME_RE.match(name):
        errors.append("--name %s: use <topic>__<role> or a bare role, lowercase kebab-case" % name)
    registered = name in agents
    if registered and not args.replace:
        errors.append("&%s is already registered (thread %s): send a follow-up brief with "
                      "`bb thread tell %s --mode queue --message-file <brief>`; use --replace only "
                      "for a crashed thread the user allowed to replace"
                      % (name, agents[name].get("thread"), agents[name].get("thread")))
    if args.replace and not registered:
        errors.append("--replace: &%s is not registered" % name)

    role_file, role_tier, role_env, read_only, what = ROLES.get(args.role) or (None, None, None, False, "")
    if args.role == "custom":
        for flag in ("what", "tier", "env"):
            if not getattr(args, flag):
                errors.append("--role custom needs --%s" % flag)
    what = args.what or what

    if args.role == "scout" and not args.works_for:
        errors.append("--role scout needs --works-for <agent>")
    if args.works_for and args.works_for.startswith("&"):
        errors.append("--works-for %s: give the name without '&'" % args.works_for)

    # tier and model
    tier = args.tier or role_tier
    model = None
    if not tiers.get("provider"):
        errors.append("no provider in the tier map: run `moe.py setup --provider ...`")
    if tier:
        model = tiers.get(tier)
        if not model:
            errors.append("no %s model in the tier map: run `moe.py setup --%s <model id>`" % (tier, tier))

    # environment
    env = args.env or role_env
    if env == "builder":
        if "__" in name:
            env = "of:%s__build" % name.split("__")[0]
        else:
            errors.append("--env: no topic in --name %s to find its builder; give --env of:<agent>" % name)
            env = None
    env_flags, where = [], None
    if env == "lead":
        if not lead.get("environment"):
            errors.append("no Lead environment in %s: run `moe.py setup`" % team_path(root))
        else:
            env_flags = ["--environment", lead["environment"]]
            where = "The Lead's worktree `%s`, branch `%s`, shared with the Lead's standing agents." % (
                lead.get("worktree"), lead.get("branch"))
    elif env == "new-worktree":
        if not lead.get("isGitRepo"):
            errors.append("--env new-worktree: the Lead's environment is not a git repo")
        else:
            ref = args.base or "HEAD"
            sha = resolve_commit(lead["worktree"], ref)
            if not sha:
                errors.append("--base %s: not a commit in %s" % (ref, lead["worktree"]))
            else:
                env_flags = ["--new-environment", "worktree", "--base-branch", sha]
                where = ("A new worktree from commit `%s` (%s). Your branch is your own."
                         % (sha, "the Lead's HEAD" if not args.base else args.base))
    elif env and env.startswith("of:"):
        owner = env[3:].lstrip("&")
        entry = agents.get(owner)
        if not entry or not entry.get("environment"):
            errors.append("--env %s: &%s is not registered with an environment" % (env, owner))
        else:
            path = environment_path(entry["environment"])
            env_flags = ["--environment", entry["environment"]]
            where = "`&%s`'s worktree%s (environment `%s`), shared with its topic's agents." % (
                owner, " `%s`" % path if path else "", entry["environment"])
    elif env:
        errors.append("--env %s: use lead, new-worktree or of:<agent>" % env)
    if args.base and env != "new-worktree":
        errors.append("--base: only with --env new-worktree")
    if where and read_only:
        where += " Read-only."

    # limits
    if args.push == "yes" and args.role != "butler":
        errors.append("--push yes: only &butler pushes")
    if args.creds and not os.path.isfile(args.creds):
        errors.append("--creds %s: no such file" % args.creds)

    # peers
    peers = []
    for peer in [p.strip() for p in (args.peers or "").split(",") if p.strip()]:
        if peer.startswith("&"):
            errors.append("--peers %s: give names without '&'" % peer)
            peer = peer.lstrip("&")
        if not NAME_RE.match(peer):
            errors.append("--peers %s: not an agent name" % peer)
        peers.append(peer)

    # spawn needs the bb context
    if args.spawn:
        for var in ("BB_THREAD_ID", "BB_PROJECT_ID"):
            if not os.environ.get(var):
                errors.append("--spawn: $%s is not set" % var)

    # body
    body = ""
    if sys.stdin.isatty():
        errors.append("no body on stdin: pipe it with a quoted heredoc (<<'EOF')")
    else:
        body = sys.stdin.read().strip()
        if not body:
            errors.append("empty body on stdin")

    if errors:
        fail(errors)

    # render
    r = REFERENCES
    lead_id = lead.get("thread")
    weight = team.get("weight") or NO_WEIGHT
    files = "`%s/roles/common.md`" % r
    if role_file:
        files += " and `%s/roles/%s`" % (r, role_file)
    opening = (
        "You are `&%s`, %s for %s. The Lead (`%s`, your parent thread) dispatched you. "
        "Your finished turns do not reach the Lead; send it what `common.md` lists under "
        "\"Reaching the Lead\", with `bb thread tell %s`. "
        "The user can read this thread and step in; what the user tells you here wins over this brief. "
        "Read and follow %s. Storage root: `%s`. Weight: %s."
        % (name, what, args.task, lead_id, lead_id, files, root, weight)
    )

    limits = [
        "- May start: %s." % (args.start or "nothing"),
        "- Commit: %s. Push: %s." % (
            "yes, on your branch" if args.commit == "yes" else "no",
            "yes, plain" if args.push == "yes" else "no"),
        "- Credentials: %s." % ("`%s`" % args.creds if args.creds else "none"),
    ]

    team_lines = ["- Lead: `%s`, your parent thread." % lead_id]
    if args.works_for:
        boss = args.works_for.lstrip("&")
        boss_id = agents.get(boss, {}).get("thread")
        team_lines.append("- You work for `&%s`: %s." % (
            boss, "`%s`" % boss_id if boss_id else "not spawned yet"))
    for peer in peers:
        pid = agents.get(peer, {}).get("thread")
        team_lines.append("- `&%s`: %s." % (peer, "`%s`" % pid if pid else "not spawned yet"))
    team_lines.append("- Every thread ID: `%s`." % team_path(root))

    text = "\n\n".join([
        opening,
        body,
        "## Where you work\n\n" + where,
        "## Limits\n\n" + "\n".join(limits),
        "## Team\n\n" + "\n".join(team_lines),
    ]) + "\n"

    # save
    briefs = os.path.join(root, "briefs")
    os.makedirs(briefs, exist_ok=True)
    if registered:
        numbers = [int(m.group(1)) for f in os.listdir(briefs)
                   for m in [re.match(re.escape(name) + r"-(\d+)-", f)] if m]
        nn = max(numbers, default=0) + 1
    else:
        nn = 1  # drafts of an unspawned agent are overwritten
    path = os.path.join(briefs, "%s-%02d-%s.md" % (name, nn, slugify(args.task)))
    with open(path, "w") as f:
        f.write(text)

    spawn = ["bb", "thread", "spawn", "--project", os.environ.get("BB_PROJECT_ID", "<project>"),
             "--parent-self", "--title", args.title or "&" + name,
             "--provider", tiers["provider"], "--model", model, "--reasoning-level", "high",
             "--parent-notifications", "stuck"] + env_flags + ["--prompt-file", path, "--json"]

    print("brief: %s" % path)
    if not args.spawn:
        print("dry run, nothing spawned. Spawn with the same flags plus --spawn, or run:")
        print("  " + " ".join(shell_quote(a) for a in spawn))
        return

    code, out, err = run(spawn)
    if code != 0:
        print("error: bb thread spawn failed (exit %d); the brief is saved, nothing registered:\n%s"
              % (code, (err or out).strip()), file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    thread = data.get("thread", data)
    thread_id = thread.get("id")
    env_id = thread.get("environmentId") or (data.get("environment") or {}).get("id")
    if not thread_id:
        # bb exited 0, so the agent may exist: never claim nothing was spawned
        print("error: spawned, but not registered: bb thread spawn printed no thread ID. "
              "Check `bb thread list` before you spawn again. The brief is %s. bb printed:\n%s"
              % (path, out.strip()), file=sys.stderr)
        sys.exit(1)
    entry = {
        "thread": thread_id,
        "environment": env_id,
        "role": args.role,
        "model": model,
        "task": args.task,
        "brief": path,
        "spawned": now(),
    }
    if args.works_for:
        entry["worksFor"] = args.works_for.lstrip("&")
    if registered:
        entry["replaces"] = agents[name].get("thread")
    team = load_team(root)  # re-read right before the write
    team.setdefault("agents", {})[name] = entry
    save_team(root, team)
    print("spawned &%s: thread %s, environment %s, model %s; registered in %s"
          % (name, thread_id, env_id, model, team_path(root)))


def shell_quote(s):
    return s if re.match(r"^[A-Za-z0-9_./:=@%+-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


def fail(errors):
    print("error: nothing written or spawned", file=sys.stderr)
    for e in errors:
        print("  - " + e, file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- main


def main():
    parser = argparse.ArgumentParser(
        prog="moe.py", description=__doc__.split("\n\n")[0] + "\n\n" + __doc__.split("\n\n")[1],
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="record the Lead's IDs, the tier map and the weight",
                       description="Create or update S/logs/team.json. The first run records the "
                                   "Lead's thread, project, environment and worktree from bb, and "
                                   "needs --provider, --stronger and --mid. Later runs change only "
                                   "the fields given.")
    s.add_argument("--provider", help="provider ID for every spawn")
    s.add_argument("--stronger", metavar="MODEL", help="model ID of the stronger tier")
    s.add_argument("--mid", metavar="MODEL", help="model ID of the mid tier")
    s.add_argument("--weight", choices=WEIGHTS, help="the job's weight, once set after the debrief")
    s.set_defaults(func=cmd_setup)

    b = sub.add_parser(
        "brief", help="render and save a brief; with --spawn, spawn and register the agent",
        description="Render a brief: an opening, the Markdown body from stdin, then Where you work, "
                    "Limits and Team. Save it as S/briefs/<name>-NN-<task>.md. Without --spawn it is "
                    "a dry run: it saves the brief and prints the spawn command. With --spawn it "
                    "spawns the agent with --parent-notifications stuck and registers it in "
                    "S/logs/team.json. Every bad flag is reported at once, and then nothing is "
                    "written or spawned. Tier and environment default by role.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    b.add_argument("--name", help="agent name without '&', e.g. auth__build, butler")
    b.add_argument("--role", help="one of: %s; custom has no role file" % ", ".join(ROLES))
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
    b.add_argument("--replace", action="store_true",
                   help="spawn under a registered name: only for a crashed thread the user allowed to replace")
    b.add_argument("--spawn", action="store_true", help="spawn and register; without it, a dry run")
    b.set_defaults(func=cmd_brief)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
