#!/usr/bin/env python3
"""Dispatch helper for the bb-moe Lead.

`models` lists the provider's models for the tier map. `setup` records the Lead's
IDs, the model tier map and the weight in S/logs/team.json. `brief` renders an
agent's brief from flags plus a Markdown body on stdin and templates/brief/, saves
it as S/briefs/<name>-NN-<task>.md and, with --spawn, spawns the agent and adds it
to the team registry in S/logs/team.json. `follow-up` sends a later brief to a
registered agent; `tell` sends a short message. `status`, `show`, `output`, `log`
and `wait` read the team; `retry`, `compact` and `stop` act on an agent.

S is the Lead's storage root ($BB_THREAD_STORAGE). Run it from the Lead's
thread; every verb except the first `setup`, and `setup --title` alone (which only renames
the calling thread), refuses from any other thread.
Agents use moe-agent.py. Python 3 standard library only.
"""

import argparse
import os
import sys
import time

from moelib import brief as brieflib
from moelib import messaging
from moelib import team as teamlib
from moelib import templates
from moelib.runtime import BbError, BbRuntime
from moelib.templates import TemplateError
from moelib.util import Failure, die, now, read_stdin_body, shell_quote

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
AGENT_CLI = "python3 " + shell_quote(os.path.join(SCRIPTS, "moe-agent.py"))

EPILOG = """\
examples:
  moe-lead.py setup --provider claude-code --stronger claude-opus-5-5 --mid claude-sonnet-5-5
  moe-lead.py setup --weight light
  moe-lead.py models

  moe-lead.py brief --name auth__build --role build --task 'OAuth sign-in' \\
    --commit no --push no --start 'dev server on port 3000' \\
    --peers auth__qa,butler --spawn <<'EOF'
  ## The user's request, word for word
  "<exact quote>"
  ...
  EOF

  moe-lead.py follow-up --name auth__build --task 'fix round 1' <<'EOF'
  User: "<exact quote>". ...
  EOF

  moe-lead.py tell auth__qa --now <<'EOF'
  <at most 8 lines or 1200 characters>
  EOF

  moe-lead.py status
  moe-lead.py wait auth__build --timeout 20m
  moe-lead.py retry auth__build

The body comes only from stdin, through a quoted heredoc (<<'EOF'): inside
double quotes the shell runs backticks and $(...) before the script sees them.
Run each call as one plain command.
"""

RETRY_LIMIT = 3
KINDS = {  # from-lead/<kind>.md: the variables its template declares
    "compact-the-lead": lambda: {"agent_cli": AGENT_CLI},
}
WAIT_WORDS = {
    0: "idle",
    2: "timeout: still working when the wait ended",
    4: "errored: the thread is in error and nothing queued will recover it; read "
       "`moe-lead.py log <name>`, then `moe-lead.py retry <name>`",
}


# ---------------------------------------------------------------- setup


def cmd_setup(args, rt):
    if args.title and not any((args.provider, args.stronger, args.mid, args.weight)):
        # SKILL.md step 1: the title comes before the tier map, so it needs no team.json
        rt.set_title(args.title)
        print("title set: %s" % args.title)
        return 0
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
    if args.title:
        rt.set_title(args.title)
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
    root, team, me = lead_team(rt)

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
        raise Failure("spawned, but not registered: bb printed no thread ID. Run "
                      "`moe-lead.py status`: a child thread not in the registry is listed there; check it before you spawn again. The brief is %s. bb printed:\n%s"
                      % (path, spawned["raw"].strip()), exit_code=1)
    # Register first, so a crash or a slow environment lookup cannot leave a running agent unregistered
    entry = {
        "thread": spawned["thread"],
        "environment": spawned["environment"],
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
    environment = spawned["environment"] or spawned_environment(rt, spawned)
    if environment and not entry["environment"]:
        team = teamlib.load_team(root)
        team["agents"][name]["environment"] = environment
        teamlib.save_team(root, team)
    print("spawned &%s: thread %s, environment %s, model %s; registered in %s"
          % (name, spawned["thread"], environment, plan["model"], teamlib.team_path(root)))
    if not environment:
        print("warning: bb gave no environment ID for &%s, so `--env of:%s` will not work until it is "
              "added to %s" % (name, name, teamlib.team_path(root)), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- models


def cmd_models(args, rt):
    me = rt.whoami()
    project = me.get("project")
    if not project:
        raise Failure("no project: run this from the Lead's bb thread")
    provider, why = choose_provider(rt, me)
    models = rt.models(provider, project)
    print("provider: %s (%s)" % (provider, why))
    if not models:
        print("no models listed for %s" % provider)
        return 0
    rows = [("model", "name", "default", "high", "description")]
    for m in models:
        efforts = m.get("efforts")
        rows.append((m.get("id") or "", m.get("name") or "",
                     "yes" if m.get("is_default") else "", "" if efforts is None else
                     ("yes" if "high" in efforts else "no"), (m.get("description") or "")[:60]))
    print_table(rows)
    print("Pick the tiers by SKILL.md, setup step 6, then run: moe-lead.py setup --provider %s "
          "--stronger <model> --mid <model>" % provider)
    return 0


def choose_provider(rt, me):
    """The user's default provider when it is available, else this thread's own."""
    default = rt.default_provider()
    if default:
        if any(p["id"] == default and p["available"] for p in rt.providers()):
            return default, "the user's default"
        reason = "the user's default, %s, is not available" % default
    else:
        reason = "the user has no default provider"
    own = rt.show(me["thread"])["provider"]
    if not own:
        raise Failure("%s, and this thread's own provider is unknown" % reason)
    return own, "this thread's own: %s" % reason


def print_table(rows):
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip())


# ---------------------------------------------------------------- follow-up and tell


def lead_team(rt):
    """(root, team, me) for a verb that runs only from the Lead's thread."""
    me = rt.whoami()
    root = me.get("storage")
    if not root:
        raise Failure("no storage root: run this from the Lead's bb thread")
    team = teamlib.load_team(root)
    if team is None:
        raise Failure("no %s: run `moe-lead.py setup` first (SKILL.md, setup step 6)" % teamlib.team_path(root))
    teamlib.require_lead(team, me, root)
    return root, team, me


def send_from_lead(rt, root, name, thread, text, body, kind, now_flag):
    result = messaging.send(rt, root, sender="lead", to=name, to_thread=thread, text=text, body=body,
                            kind=kind, mode="steer" if now_flag else "queue")
    print("delivered to &%s (%s): %s%s" % (name, thread, result["delivery"],
                                          ", id " + result["id"] if result["id"] else ""))


def cmd_follow_up(args, rt):
    root, team, _ = lead_team(rt)
    name = args.name.lstrip("&")
    thread = teamlib.lookup(team, name)
    body = read_stdin_body("brief")
    text = templates.render("brief/follow-up", body=body)
    nn = brieflib.next_brief_number(root, name)
    path = brieflib.write_brief(root, name, nn, args.task, text + "\n")
    print("brief: %s" % path)
    send_from_lead(rt, root, name, thread, text, body, "follow-up", args.now)
    return 0


def cmd_tell(args, rt):
    root, team, _ = lead_team(rt)
    name = args.name.lstrip("&")
    thread = teamlib.lookup(team, name)
    if args.kind:
        body = None
        text = templates.render("from-lead/" + args.kind, **KINDS[args.kind]())
    else:
        body = read_stdin_body("message")
        lines = body.count("\n") + 1
        if lines > messaging.MAX_LINES or len(body) > messaging.MAX_CHARS:
            raise Failure("message too long: %d lines, %d characters (limit %d lines, %d characters). "
                          "Send a longer text with `moe-lead.py follow-up`."
                          % (lines, len(body), messaging.MAX_LINES, messaging.MAX_CHARS))
        text = templates.render("from-lead/message", body=body)
    send_from_lead(rt, root, name, thread, text, body, args.kind or "tell", args.now)
    return 0


# ---------------------------------------------------------------- status, show, output, log


def last_where(records, test):
    found = [r for r in records if test(r)]
    return found[-1] if found else None


def agent_status(rt, entry, children):
    status = children.get(entry.get("thread"))
    if status:
        return status
    try:
        return rt.show(entry["thread"]).get("status") or "unknown"
    except BbError:
        return "unknown"


def context_line(rt):
    try:
        ctx = rt.context_self()
    except BbError:
        ctx = {}
    used, window = ctx.get("used_tokens"), ctx.get("window")
    if used is None:
        return "Lead context: not available"
    if window:
        return "Lead context: %d of %d tokens (%d%%)" % (used, window, round(100 * used / window))
    return "Lead context: %d tokens" % used


def cmd_status(args, rt):
    root, team, _ = lead_team(rt)
    agents = team.get("agents") or {}
    names = sorted(agents)
    if args.name:
        name = args.name.lstrip("&")
        teamlib.lookup(team, name)
        names = [name]
    child_list = rt.list_children()
    children = {c["id"]: c["status"] for c in child_list}
    # a failed or unconfirmed send is not a message the Lead got
    messages = [m for m in teamlib.read_messages(root) if m.get("delivery") not in ("failed", "unconfirmed")]
    rows = [("agent", "thread", "status", "last message from it", "flag")]
    for name in names:
        entry = agents[name]
        status = agent_status(rt, entry, children)
        last = last_where(messages, lambda m: m.get("from") == name)
        since = max([entry.get("spawned") or ""] +
                    [m["time"] for m in messages if m.get("from") == "lead" and m.get("to") == name])
        sent = last and last.get("time", "") >= since  # any kind, to anyone: a hand-off counts
        flag = "idle, sent nothing" if status == "idle" and not sent else ""
        said = ("%s to %s: %s %s" % (last["time"], last.get("to"), last.get("kind"),
                                      (last.get("first") or "")[:40]) if last else "none")
        rows.append(("&" + name, entry.get("thread"), status, said, flag))
    if not args.name:
        known = {e.get("thread") for e in agents.values()}
        for c in child_list:
            if c["id"] not in known:
                rows.append(("(not registered)", c["id"], c.get("status") or "unknown",
                             (c.get("title") or "")[:50], ""))
    print_table(rows)
    print(context_line(rt))
    return 0


def agent_thread(rt, args):
    root, team, _ = lead_team(rt)
    return args.name.lstrip("&"), teamlib.lookup(team, args.name)


def cmd_show(args, rt):
    name, thread = agent_thread(rt, args)
    shown = rt.show(thread)
    env = shown.get("environment") or {}
    print("&%s: %s" % (name, thread))
    print("status: %s" % shown.get("status"))
    print("provider: %s" % shown.get("provider"))
    print("environment: %s, path %s, branch %s" % (shown.get("environment_id"), env.get("path"),
                                                  env.get("branch")))
    return 0


def cmd_output(args, rt):
    _, thread = agent_thread(rt, args)
    print(rt.output(thread))
    return 0


def cmd_log(args, rt):
    _, thread = agent_thread(rt, args)
    print(rt.log(thread, everything=args.all), end="")
    return 0


# ---------------------------------------------------------------- wait, retry, compact, stop


def cmd_wait(args, rt):
    name, thread = agent_thread(rt, args)
    result = rt.wait(thread, args.timeout)
    code = result["exit"]
    words = WAIT_WORDS.get(code, "exit %d" % code).replace("<name>", name)
    print("&%s: %s" % (name, words))
    return code


def cmd_retry(args, rt):
    root, team, _ = lead_team(rt)
    name = args.name.lstrip("&")
    thread = teamlib.lookup(team, name)
    messages = teamlib.read_messages(root)
    heard = [i for i, m in enumerate(messages) if m.get("from") == name]
    since = heard[-1] + 1 if heard else 0
    tries = sum(1 for m in messages[since:] if m.get("kind") == "retry" and m.get("to") == name)
    if tries >= RETRY_LIMIT:
        raise Failure("&%s: %d retries since it last reported, and it has not recovered. Do not retry "
                      "again: tell the user and wait; the cause may be outside bb "
                      "(SKILL.md, \"Claims, permissions, failures\")." % (name, tries), exit_code=1)
    rt.retry(thread)
    teamlib.append_message(root, {"from": "lead", "to": name, "toThread": thread, "kind": "retry",
                                  "delivery": "retried", "first": "retry %d of %d" % (tries + 1, RETRY_LIMIT)})
    print("retry %d of %d sent to &%s (%s)" % (tries + 1, RETRY_LIMIT, name, thread))
    return 0


def cmd_compact(args, rt):
    name, thread = agent_thread(rt, args)
    rt.compact(thread)
    print("&%s (%s): compacted" % (name, thread))
    return 0


def cmd_stop(args, rt):
    name, thread = agent_thread(rt, args)
    rt.stop(thread)
    print("&%s (%s): stopped" % (name, thread))
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
    s.add_argument("--title", help="set this thread's title, e.g. '🧾 CSV export'; alone it needs no "
                                   "team.json, so it can come before the tier map. Set it once")
    s.set_defaults(func=cmd_setup)

    m = sub.add_parser("models", help="the provider and its models, for the tier map",
                       description="Print the provider to use (the user's default when it is available, "
                                   "else this thread's own) and its models: ID, name, whether it is the "
                                   "provider's default, whether it lists the 'high' reasoning effort, "
                                   "and its description. Picking the tiers stays with you "
                                   "(SKILL.md, setup step 6).")
    m.set_defaults(func=cmd_models)

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

    f = sub.add_parser(
        "follow-up", help="send a later brief to a registered agent",
        description="Send the body on stdin to a registered agent as a follow-up brief, queued until "
                    "it is free. The brief is saved as S/briefs/<name>-NN-<task>.md, numbered on from "
                    "the agent's last one. Template: templates/brief/follow-up.md.")
    f.add_argument("--name", required=True, help="the agent, without '&'")
    f.add_argument("--task", required=True, help="the round in a few words; the brief's file name")
    f.add_argument("--now", action="store_true",
                   help="steer the agent's current turn instead of queueing; only to interrupt it")
    f.set_defaults(func=cmd_follow_up)

    t = sub.add_parser(
        "tell", help="send a short message to a registered agent",
        description="Send a message of at most %d lines or %d characters to a registered agent, queued, "
                    "with a sender line. The text comes from stdin, or from a template with --kind "
                    "(templates/from-lead/). A longer text is a follow-up brief."
                    % (messaging.MAX_LINES, messaging.MAX_CHARS))
    t.add_argument("name", help="the agent, without '&'")
    t.add_argument("--kind", choices=sorted(KINDS), help="send this template's text instead of stdin")
    t.add_argument("--now", action="store_true",
                   help="steer the agent's current turn instead of queueing; only to interrupt it")
    t.set_defaults(func=cmd_tell)

    st = sub.add_parser(
        "status", help="every agent: bb status, its last message, and who went quiet",
        description="One table: each registered agent, its thread, its bb status, the last message it "
                    "sent (from S/logs/messages.jsonl), and a flag 'idle, sent nothing' for an idle "
                    "agent that has sent no message at all (a final answer, a hand-off, any tell) since "
                    "it was spawned or you last told it something: it may have forgotten its tell. "
                    "A send that failed does not count. Child threads that are not in the registry "
                    "get a row too. Then your own context use.")
    st.add_argument("name", nargs="?", help="only this agent")
    st.set_defaults(func=cmd_status)

    for verb, func, text in (
            ("show", cmd_show, "an agent's bb status, provider and environment"),
            ("output", cmd_output, "an agent's full final answer (notifications are truncated)"),
            ("log", cmd_log, "an agent's event log")):
        p = sub.add_parser(verb, help=text, description=text[0].upper() + text[1:] + ".")
        p.add_argument("name", help="the agent, without '&'")
        if verb == "log":
            p.add_argument("--all", action="store_true", help="the whole log")
        p.set_defaults(func=func)

    w = sub.add_parser(
        "wait", help="block until an agent is idle",
        description="Block until the agent is idle, only when your very next step needs its result. "
                    "Exit 0: idle. Exit 2: timeout. Exit 4: the thread is in error and nothing "
                    "queued will recover it. The words are printed.")
    w.add_argument("name", help="the agent, without '&'")
    w.add_argument("--timeout", default="20m", help="how long to wait, e.g. 20m (default 20m)")
    w.set_defaults(func=cmd_wait)

    r = sub.add_parser(
        "retry", help="retry an agent's failed turn, at most %d times" % RETRY_LIMIT,
        description="Retry a failed turn (after a spend limit or an outage). At most %d times for an "
                    "agent until it reports again; the next call refuses: tell the user."
                    % RETRY_LIMIT)
    r.add_argument("name", help="the agent, without '&'")
    r.set_defaults(func=cmd_retry)

    c = sub.add_parser("compact", help="compact an idle agent's context",
                       description="Compact an agent's context. bb allows it only on an idle or errored "
                                   "thread.")
    c.add_argument("name", help="the agent, without '&'")
    c.set_defaults(func=cmd_compact)

    sp = sub.add_parser("stop", help="stop an agent's work and release its runtime",
                        description="Stop an agent's work and release its runtime. Archiving or deleting "
                                    "agent threads and worktrees is the user's call.")
    sp.add_argument("name", help="the agent, without '&'")
    sp.set_defaults(func=cmd_stop)
    return parser


def main(argv=None, runtime=None):
    args = build_parser().parse_args(argv)
    rt = runtime or BbRuntime()
    try:
        return args.func(args, rt)
    except Failure as f:
        die(f)
    except messaging.NotDelivered as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    except BbError as e:
        print("error: bb: %s" % e, file=sys.stderr)
        return 1
    except TemplateError as e:
        print("error: nothing written or spawned\n  - template: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
