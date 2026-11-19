"""Sending a message: size limit, sender line, one retry, a line in messages.jsonl.

Also the chain kinds (`tell --kind`): each message of the review chain is a template
under templates/chain/ (or templates/lead/), its fields are flags, and every commit
is checked with `git rev-parse` in the caller's worktree.
"""

import os
import re
import subprocess
import time

from moelib import team as teamlib
from moelib import templates
from moelib.runtime import BbError

MAX_LINES = 8
MAX_CHARS = 1200
ATTEMPTS = 2  # one try and one retry


class NotDelivered(Exception):
    pass


class Unconfirmed(NotDelivered):
    """bb exited 0 but its answer did not say sent or queued. The message may have arrived,
    so it is never resent."""


def topic_of(name):
    return name.split("__")[0] if name and "__" in name else None


def check_short(text):
    """Return an error text when `text` is too long for a message to the Lead, else None."""
    lines = text.count("\n") + 1
    if lines > MAX_LINES or len(text) > MAX_CHARS:
        return ("message too long: %d lines, %d characters (limit %d lines, %d characters). Put the "
                "detail in a report under S/reports/ and send its path with the verdict."
                % (lines, len(text), MAX_LINES, MAX_CHARS))
    return None


def with_sender_line(sender_name, body, done=False):
    ref = "common/sender-line-done" if done else "common/sender-line"
    return templates.render(ref, agent_name=sender_name) + "\n\n" + body


def send(runtime, root, *, sender, to, to_thread, text, body=None, kind=None,
         topic=None, commit=None, mode="queue", compact_first=False, attempts=ATTEMPTS,
         extra=None, sleep=time.sleep):
    """Send `text` to `to_thread`. A bb error or refusal is retried (`attempts` tries in all);
    an exit-0 answer without sent or queued is not (it may have been queued): it raises
    Unconfirmed. Every attempt adds a line to messages.jsonl.
    Returns {"delivery", "id", "attempts"}; raises NotDelivered with bb's error."""
    first = (body if body is not None else text).strip().split("\n", 1)[0][:160]
    topic = topic or topic_of(sender if sender != "lead" else to) or topic_of(to)
    last_error = None
    for attempt in range(1, attempts + 1):
        record = dict(extra or {}, **{"from": sender, "to": to, "toThread": to_thread, "kind": kind,
                                      "topic": topic, "commit": commit, "mode": mode,
                                      "attempt": attempt, "first": first})
        try:
            result = runtime.tell(to_thread, text, mode, compact_first=compact_first)
        except BbError as e:
            last_error = e
            teamlib.append_message(root, dict(record, delivery="failed", error=str(e)))
            if attempt < attempts:
                sleep(1.0)
            continue
        if result.get("delivery") not in ("sent", "queued"):
            teamlib.append_message(root, dict(record, delivery="unconfirmed",
                                              error="bb answered delivery %r" % result.get("delivery")))
            raise Unconfirmed("UNCONFIRMED to %s (%s): bb exited 0 but did not say sent or queued, so "
                              "the message may have arrived. Not resent: look in the target's log "
                              "before you send it again." % (to, to_thread))
        teamlib.append_message(root, dict(record, delivery=result["delivery"], messageId=result.get("id")))
        return {"delivery": result["delivery"], "id": result.get("id"), "attempts": attempt}
    raise NotDelivered("NOT delivered to %s (%s) after %d %s: %s"
                       % (to, to_thread, attempts, "try" if attempts == 1 else "tries", last_error))


# ---------------------------------------------------------------- chain kinds


class Kind:
    """One message of the review chain: its template, the flags it needs, and whether the
    body (stdin) is part of it.

    `variant`: (optional flag, template used when it is given), for a message with two
    wordings, each its own file. `working_tree`: `--commit working-tree` is accepted."""

    def __init__(self, template, required, optional=(), body=None, variant=None, working_tree=False):
        self.template = template
        self.required = tuple(required)
        self.optional = tuple(optional)
        self.body = body  # template variable that takes the stdin text, or None
        self.variant = variant
        self.working_tree = working_tree


_CHAIN = ("topic", "commit", "branch", "base", "builder")
KINDS = {
    "ready-for-qa": Kind("chain/ready-for-qa", ("topic", "summary"), ("commit",),
                         variant=("commit", "chain/ready-for-qa-commit")),
    "qa-passed": Kind("chain/qa-passed", _CHAIN, working_tree=True),
    "review-findings": Kind("chain/review-findings", _CHAIN + ("review",), working_tree=True),
    "committed": Kind("chain/committed", ("topic", "commit", "branch")),
    "review-passed": Kind("chain/review-passed", _CHAIN),
    "merged": Kind("chain/merged", ("commit",)),
    "main-qa-passed": Kind("chain/main-qa-passed", ("commit",)),
    "main-qa-failed": Kind("chain/main-qa-failed", ("commit",), body="defects"),
    "pushed": Kind("chain/pushed", ("commit",)),
}
# The flag names a kind may take, with the template variable each fills (default: the same name).
FIELD_VARIABLE = {"builder": "builder_thread"}
FIELD_HELP = {
    "topic": "the topic (default: the first part of your own name)",
    "commit": "a commit: a SHA git knows, checked in this worktree and sent in full",
    "base": "the topic's base commit, checked like --commit",
    "branch": "the topic's branch",
    "builder": "the builder's thread ID (default: from the registry, `&<topic>__build`)",
    "summary": "what changed, in one line",
    "review": "the review report number NN: S/reports/<topic>__review-NN.md",
}
WORKING_TREE = "working tree"


def resolve_commit(ref, cwd=None):
    """The full SHA that `ref` names in the git repo at `cwd` (default: the current directory).
    Raises ValueError with the reason."""
    try:
        p = subprocess.run(["git", "-C", cwd or ".", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise ValueError("git is not installed, so %s cannot be checked" % ref)
    sha = p.stdout.strip()
    if p.returncode != 0 or not sha:
        raise ValueError("%s is not a commit git knows in %s" % (ref, cwd or "this directory"))
    return sha


def kind_variables(kind_name, given, *, sender_topic, registered, root, cwd=None):
    """Check the flags `given` ({flag: value}, None when absent) against the kind and return
    (template ref, template variables). Raises ValueError with every problem, so the
    caller sends nothing."""
    kind = KINDS[kind_name]
    allowed = set(kind.required) | set(kind.optional)
    errors = []
    values = {k: v for k, v in given.items() if v is not None}
    for flag in sorted(values):
        if flag not in allowed:
            errors.append("--%s is not used by kind %s" % (flag, kind_name))
    if "topic" in kind.required and "topic" not in values and sender_topic:
        values["topic"] = sender_topic
    if "builder" in kind.required and "builder" not in values and values.get("topic"):
        entry = registered.get("%s__build" % values["topic"]) or {}
        if entry.get("thread"):
            values["builder"] = entry["thread"]
    for flag in kind.required:
        if flag not in values:
            errors.append("kind %s needs --%s (%s)" % (kind_name, flag, FIELD_HELP.get(flag, flag)))
    for flag in ("commit", "base"):
        if flag not in values:
            continue
        if flag == "commit" and kind.working_tree and values[flag] in ("working-tree", WORKING_TREE):
            values[flag] = WORKING_TREE
            continue
        try:
            values[flag] = resolve_commit(values[flag], cwd)
        except ValueError as e:
            errors.append("--%s: %s" % (flag, e))
    if "review" in values:
        if not re.fullmatch(r"\d{2}", values["review"]):
            errors.append("--review: two digits, such as 01")
        elif values.get("topic"):
            path = "%s/reports/%s__review-%s.md" % (root, values["topic"], values["review"])
            if not os.path.exists(path):
                errors.append("--review: %s does not exist" % path)
    if errors:
        raise ValueError("\n".join(errors))
    template = kind.template
    if kind.variant and kind.variant[0] in values:
        template = kind.variant[1]
    return template, {FIELD_VARIABLE.get(k, k): v for k, v in values.items()}
