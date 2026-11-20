#!/usr/bin/env python3
"""Messages and lookups for bb-moe agents.

`tell <name>` sends a message to another agent; `tell <name> --kind K` sends one of
the review chain's fixed messages (templates/chain/). `tell-lead` sends one to the
Lead; `--done` marks your final answer. `who` shows the team. `compact-lead` is
for &butler. Each message body comes from stdin, through a quoted heredoc. Run each
call as one plain command.

The team registry is found from this thread's parent (the Lead); `--root S`
overrides that. Python 3 standard library only.
"""

import argparse
import sys
import time

from moelib import messaging
from moelib import team as teamlib
from moelib import templates
from moelib import waiting
from moelib.brief import ROLES
from moelib.runtime import BbError, BbRuntime
from moelib.templates import TemplateError
from moelib.util import Failure, die, read_stdin_body

EPILOG = """\
examples:
  moe-agent.py tell auth__qa <<'EOF'
  ready for QA: <what changed>
  EOF

  moe-agent.py tell-lead --done <<'EOF'
  <verdict first, at most 8 lines or 1200 characters; the rest goes in a report under S/reports/>
  EOF

  moe-agent.py tell auth__qa --kind ready-for-qa --summary 'CSV export, 4 files'

  moe-agent.py tell lead --kind review-passed --commit <SHA> --base <SHA> --branch <X>

  moe-agent.py who auth__qa

  moe-agent.py wait-user 'Q2 - model tier'
  moe-agent.py wait-user --act 'API key for the CSV store'
  moe-agent.py user-answered

The body comes only from stdin, through a quoted heredoc (<<'EOF'): inside
double quotes the shell runs backticks and $(...) before the script sees them.
A --kind message has no free body (except main-qa-failed: the defects) and sends
nothing when a flag is missing or a commit is unknown.
"""

COMPACT_TRIES = 3
WAIT_USER_HELP = ("Before you end a turn waiting on the user: put ❓ (a question, references/ask-user.md) "
                  "or ❗️ (--act: the user must do something else) in front of your own title, replacing "
                  "the other marker, push one notification that opens this thread, and print the "
                  "`waiting for user on <what>` line to end the turn on. A bb failure is a warning; the "
                  "turn still ends on the line.")
KIND_HELP = {
    "ready-for-qa": "builder to QA; with --commit once commits are allowed",
    "qa-passed": "QA to the reviewer (later fixes: to the last gate); --commit may be working-tree",
    "review-findings": "reviewer to the review-skeptic",
    "committed": "builder to the last gate: the tested tree is committed",
    "review-passed": "last gate to &butler (landing allowed) or to the Lead (tell lead)",
    "merged": "&butler to &main__qa",
    "main-qa-passed": "&main__qa to &butler",
    "main-qa-failed": "&main__qa to &butler and the builder; the defects on stdin",
    "pushed": "&butler to the next link",
}


def _kinds_text():
    lines = ["With --kind, the message is a template (templates/chain/, templates/lead/) filled from "
             "flags. Nothing is sent when a flag is missing or a commit is unknown. A kind has no "
             "free body, except main-qa-failed (the defects, on stdin). `lead` is a valid name with "
             "a kind. A kind to a `<topic>__<role>` name that is not spawned yet goes to the Lead "
             "instead, and the script prints the line to end your turn on.", "", "Kinds:"]
    for name in sorted(messaging.KINDS):
        kind = messaging.KINDS[name]
        flags = " ".join("--" + f for f in kind.required if f not in ("topic", "builder"))
        flags += "".join(" [--%s]" % f for f in kind.optional)
        if kind.body:
            flags += " + stdin"
        lines.append("  %-16s %s" % (name, flags))
        lines.append("  %-16s %s" % ("", KIND_HELP[name]))
    lines += ["", "--topic and --builder default to your own name's topic and the registered "
                  "&<topic>__build."]
    return "\n".join(lines)


def _deliver(rt, ctx, to, to_thread, body, kind, mode, done=False, **more):
    text = messaging.with_sender_line(ctx.name, body, done=done)
    return messaging.send(rt, ctx.root, sender=ctx.name, to=to, to_thread=to_thread, text=text,
                          body=body, kind=kind, mode=mode, **more)


def _report(result, who, thread):
    print("delivered to %s (%s): %s%s" % (who, thread, result["delivery"],
                                         ", id " + result["id"] if result["id"] else ""))


def _is_link_name(name):
    """Looks like a chain agent, `<topic>__<role>`: a name the Lead may not have spawned yet."""
    return "__" in name and name.rsplit("__", 1)[1] in ROLES


def cmd_tell(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    name = args.name.lstrip("&")
    if args.kind:
        return _tell_kind(args, rt, ctx, name)
    for flag in messaging.FIELD_HELP:
        if getattr(args, flag) is not None:
            raise Failure("--%s goes with --kind: a plain tell has no fields" % flag)
    to_thread = teamlib.lookup(ctx.team, name)
    body = read_stdin_body("message")
    result = _deliver(rt, ctx, name, to_thread, body, "tell", "steer" if args.now else "queue")
    _report(result, "&" + name, to_thread)
    return 0


def _tell_kind(args, rt, ctx, name):
    agents = ctx.team.get("agents") or {}
    given = {flag: getattr(args, flag) for flag in messaging.FIELD_HELP}
    try:
        ref, variables = messaging.kind_variables(
            args.kind, given, sender_topic=messaging.topic_of(ctx.name), registered=agents, root=ctx.root)
    except ValueError as e:
        raise Failure(str(e).split("\n"), header="error: nothing sent (kind %s):" % args.kind)
    body_variable = messaging.KINDS[args.kind].body
    if body_variable:
        variables[body_variable] = read_stdin_body(body_variable)
    body = templates.render(ref, **variables)
    commit = variables.get("commit")
    mode = "steer" if args.now else "queue"
    if name.lower() == "lead":
        lead = ctx.team.get("lead", {}).get("thread")
        if not lead:
            raise Failure("%s has no Lead recorded" % teamlib.team_path(ctx.root))
        result = _deliver(rt, ctx, "lead", lead, body, args.kind, mode, commit=commit)
        _report(result, "the Lead", lead)
        return 0
    if name in agents and agents[name].get("thread"):
        thread = agents[name]["thread"]
        result = _deliver(rt, ctx, name, thread, body, args.kind, mode, commit=commit)
        _report(result, "&" + name, thread)
        return 0
    if not _is_link_name(name):
        teamlib.lookup(ctx.team, name)  # raises, listing the registered names
    return _forward_unspawned(rt, ctx, name, args.kind, body, commit)


def _forward_unspawned(rt, ctx, name, kind, message, commit):
    """The next link is not registered: the message goes to the Lead, who spawns it with this
    message as its trigger."""
    lead = ctx.team.get("lead", {}).get("thread")
    if not lead:
        raise Failure("%s has no Lead recorded" % teamlib.team_path(ctx.root))
    body = templates.render("lead/handoff-unspawned", next=name, message=message)
    result = _deliver(rt, ctx, "lead", lead, body, "handoff-unspawned", "queue", commit=commit,
                      extra={"forKind": kind, "next": name})
    _report(result, "the Lead", lead)
    print("&%s is not spawned yet, so the Lead has your message. End your turn with: "
          "waiting for Lead on &%s" % (name, name))
    return 0


def cmd_tell_lead(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    lead = ctx.team.get("lead", {}).get("thread")
    if not lead:
        raise Failure("%s has no Lead recorded" % teamlib.team_path(ctx.root))
    body = read_stdin_body("message")
    too_long = messaging.check_short(body)
    if too_long:
        raise Failure(too_long)
    result = _deliver(rt, ctx, "lead", lead, body, "done" if args.done else "tell-lead", "queue",
                      done=args.done)
    print("delivered to the Lead (%s): %s%s" % (lead, result["delivery"],
                                               ", id " + result["id"] if result["id"] else ""))
    if args.done:
        print("Your final answer, the same text:")
        print(body)
    return 0


def cmd_wait_user(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    what = args.what.strip()
    if not what:
        raise Failure("say what you wait on: `wait-user '<what>'`")
    lines, warnings = waiting.wait_for_user(
        rt, ctx.me, "&" + ctx.name, " ".join(what.split()),
        waiting.ACTION if args.act else waiting.QUESTION)
    print("\n".join(lines))
    for w in warnings:
        print("warning: " + w, file=sys.stderr)
    return 0


def cmd_user_answered(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    print(waiting.clear_marker(rt, ctx.me))
    return 0


def cmd_compact_lead(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    if ctx.name != "butler":
        raise Failure("compact-lead is for &butler only: this thread is %s"
                      % ("&" + ctx.name if ctx.name else ctx.me.get("thread")))
    lead = ctx.team.get("lead", {}).get("thread")
    if not lead:
        raise Failure("%s has no Lead recorded" % teamlib.team_path(ctx.root))
    problem = None
    for attempt in range(1, COMPACT_TRIES + 1):
        if attempt > 1:
            time.sleep(5.0)
        try:
            waited = rt.wait(lead, args.timeout)
            if waited["exit"] == 4:
                problem = "the Lead's thread is in error with nothing queued to recover it"
                continue
            if not waited["matched"]:
                problem = "the Lead was still busy after %s" % args.timeout
                continue
            body = templates.render("lead/compacted")
            text = messaging.with_sender_line(ctx.name, body)
            result = messaging.send(rt, ctx.root, sender=ctx.name, to="lead", to_thread=lead, text=text,
                                    body=body, kind="compacted", compact_first=True, attempts=1)
        except messaging.Unconfirmed:
            raise
        except (messaging.NotDelivered, BbError) as e:
            problem = str(e)
            continue
        print("Lead compacted and told (%s): %s%s" % (lead, result["delivery"],
                                                     ", id " + result["id"] if result["id"] else ""))
        return 0
    body = templates.render("lead/not-compacted", tries=str(COMPACT_TRIES), problem=problem)
    result = _deliver(rt, ctx, "lead", lead, body, "not-compacted", "queue")
    _report(result, "the Lead", lead)
    print("Not compacted after %d tries; the Lead was told." % COMPACT_TRIES, file=sys.stderr)
    return 1


def cmd_who(args, rt):
    ctx = teamlib.agent_context(rt, args.root, need_name=False)
    agents = ctx.team.get("agents") or {}
    lead = ctx.team.get("lead", {})
    if args.name:
        name = args.name.lstrip("&")
        if name.lower() == "lead":
            print("Lead: %s, worktree %s, branch %s" % (lead.get("thread"), lead.get("worktree"),
                                                        lead.get("branch")))
            return 0
        thread = teamlib.lookup(ctx.team, name)
        e = agents[name]
        print("&%s: %s, role %s, model %s, environment %s, task: %s"
              % (name, thread, e.get("role"), e.get("model"), e.get("environment"), e.get("task")))
        return 0
    print("You: %s (%s)" % ("&" + ctx.name if ctx.name else "not registered", ctx.me.get("thread")))
    print("Lead: %s" % lead.get("thread"))
    print("Weight: %s" % ctx.team.get("weight", "not set"))
    print("Registry: %s" % teamlib.team_path(ctx.root))
    for name in sorted(agents):
        e = agents[name]
        print("&%s: %s, %s" % (name, e.get("thread"), e.get("role")))
    return 0


def build_parser():
    doc = __doc__.split("\n\n")
    parser = argparse.ArgumentParser(
        prog="moe-agent.py", description=doc[0] + "\n\n" + doc[1] + "\n\n" + doc[2],
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = argparse.ArgumentParser(add_help=False)
    root.add_argument("--root", metavar="S", help="the Lead's storage root; default: derived from this "
                                                  "thread's parent")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tell", parents=[root], help="send a message to another agent",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description="Send the body on stdin to a registered agent, queued until it is "
                                   "free, with a sender line. Names go without '&'. An unknown name "
                                   "lists the registered ones.\n\n" + _kinds_text())
    t.add_argument("name", help="the agent, e.g. auth__qa; `lead` with --kind")
    t.add_argument("--now", action="store_true",
                   help="steer the agent's current turn instead of queueing; only to interrupt it")
    t.add_argument("--kind", choices=sorted(messaging.KINDS), metavar="KIND",
                   help="send a fixed chain message instead of a free body (kinds listed above)")
    for flag in messaging.FIELD_HELP:
        t.add_argument("--" + flag, help="with --kind: " + messaging.FIELD_HELP[flag])
    t.set_defaults(func=cmd_tell)

    tl = sub.add_parser("tell-lead", parents=[root], help="send a message to the Lead",
                        description="Send the body on stdin to the Lead, queued, with a sender line. "
                                    "More than 8 lines or 1200 characters is refused: put the detail "
                                    "in S/reports/ and send its path with the verdict.")
    tl.add_argument("--done", action="store_true",
                    help="this is your final answer; the text is echoed for your own final answer")
    tl.set_defaults(func=cmd_tell_lead)

    wu = sub.add_parser("wait-user", parents=[root], help="mark your title, notify the user, wait",
                        description=WAIT_USER_HELP)
    wu.add_argument("what", help="what you wait on, e.g. 'Q2 - model tier'; it is the notification's body")
    wu.add_argument("--act", action="store_true",
                    help="the user must do something that is not answering a question: ❗️ instead of ❓")
    wu.set_defaults(func=cmd_wait_user)

    ua = sub.add_parser("user-answered", parents=[root], help="take the marker off your title",
                        description="The user answered or acted and nothing stays open: take the leading "
                                    "❓ or ❗️ off your title. Does nothing without a marker.")
    ua.set_defaults(func=cmd_user_answered)

    c = sub.add_parser("compact-lead", parents=[root], help="compact the Lead (&butler only)",
                       description="Wait until the Lead is idle, compact it and send \"Lead compacted\" "
                                   "in one bb call. At most %d tries; then tell the Lead it is not "
                                   "compacted." % COMPACT_TRIES)
    c.add_argument("--timeout", default="20m", help="how long to wait for the Lead to idle, per try")
    c.set_defaults(func=cmd_compact_lead)

    w = sub.add_parser("who", parents=[root], help="show the team, or one agent",
                       description="Without a name: you, the Lead and every registered agent. "
                                   "With a name (or 'lead'): that one.")
    w.add_argument("name", nargs="?", help="an agent, or lead")
    w.set_defaults(func=cmd_who)
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
        print("error: nothing sent\n  - template: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
