#!/usr/bin/env python3
"""Messages and lookups for bb-moe agents.

`tell <name>` sends a message to another agent. `tell-lead` sends one to the
Lead; `--done` marks your final answer. `who` shows the team. Each message body
comes from stdin, through a quoted heredoc. Run each call as one plain command.

The team registry is found from this thread's parent (the Lead); `--root S`
overrides that. Python 3 standard library only.
"""

import argparse
import sys

from moelib import messaging
from moelib import team as teamlib
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

  moe-agent.py who auth__qa

The body comes only from stdin, through a quoted heredoc (<<'EOF'): inside
double quotes the shell runs backticks and $(...) before the script sees them.
"""


def _deliver(rt, ctx, to, to_thread, body, kind, mode, done=False):
    text = messaging.with_sender_line(ctx.name, body, done=done)
    result = messaging.send(rt, ctx.root, sender=ctx.name, to=to, to_thread=to_thread, text=text,
                            body=body, kind=kind, mode=mode)
    return result


def cmd_tell(args, rt):
    ctx = teamlib.agent_context(rt, args.root)
    to_thread = teamlib.lookup(ctx.team, args.name)
    body = read_stdin_body("message")
    mode = "steer" if args.now else "queue"
    result = _deliver(rt, ctx, args.name.lstrip("&"), to_thread, body, "tell", mode)
    print("delivered to &%s (%s): %s%s" % (args.name.lstrip("&"), to_thread, result["delivery"],
                                          ", id " + result["id"] if result["id"] else ""))
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
                       description="Send the body on stdin to a registered agent, queued until it is "
                                   "free, with a sender line. Names go without '&'. An unknown name "
                                   "lists the registered ones.")
    t.add_argument("name", help="the agent, e.g. auth__qa")
    t.add_argument("--now", action="store_true",
                   help="steer the agent's current turn instead of queueing; only to interrupt it")
    t.set_defaults(func=cmd_tell)

    tl = sub.add_parser("tell-lead", parents=[root], help="send a message to the Lead",
                        description="Send the body on stdin to the Lead, queued, with a sender line. "
                                    "More than 8 lines or 1200 characters is refused: put the detail "
                                    "in S/reports/ and send its path with the verdict.")
    tl.add_argument("--done", action="store_true",
                    help="this is your final answer; the text is echoed for your own final answer")
    tl.set_defaults(func=cmd_tell_lead)

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
