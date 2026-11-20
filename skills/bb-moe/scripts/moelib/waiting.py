"""The marker and the notification for a thread that waits on the user.

A thread waiting on the user starts its own title with a marker and pushes one notification
that opens it: ❓ when it asked a question (references/ask-user.md), ❗️ when the user must do
something else. One marker at a time: a new wait replaces the old one. Clearing takes the
marker off and leaves the rest of the title as it was. Both entry points use this module.
"""

import re

from moelib.runtime import BbError

QUESTION, ACTION = "question", "action"
MARKERS = {QUESTION: "❓", ACTION: "❗️"}
VERBS = {QUESTION: "asks", ACTION: "needs you"}
BODY_LIMIT = 180  # bb cuts a notification body here
_LEADING = re.compile(r"^(?:(?:❓|❗)️?\s*)+")


def strip_marker(title):
    """The title without a leading marker (any number of them)."""
    return _LEADING.sub("", title or "")


def waiting_line(what):
    return "waiting for user on %s" % what


def wait_for_user(rt, me, label, what, kind):
    """Mark this thread's title, notify the user, and say what to end the turn on. `label` is
    `&<name>` or `Lead`; `me` is `rt.whoami()`. A bb failure is a warning on the returned
    list, not an error: the turn still ends on the waiting line. Returns (lines, warnings)."""
    marker = MARKERS[kind]
    base = strip_marker(me.get("title")) or label
    lines, warnings = [], []
    title = "%s %s" % (marker, base)
    try:
        if title != me.get("title"):
            rt.set_title(title)
        lines.append("marker set: %s" % title)
    except BbError as e:
        warnings.append("marker NOT set: %s" % e)
    try:
        rt.notify("%s %s %s" % (marker, label, VERBS[kind]), what[:BODY_LIMIT], me.get("thread"))
        lines.append("notification sent: %s %s %s" % (marker, label, VERBS[kind]))
    except BbError as e:
        warnings.append("notification NOT sent: %s" % e)
    lines.append("End your turn with: " + waiting_line(what))
    return lines, warnings


def clear_marker(rt, me):
    """Take the marker off this thread's title. Returns the line to print. Does nothing when
    there is no marker."""
    title = me.get("title") or ""
    if strip_marker(title) == title:
        return "no marker to clear"
    base = strip_marker(title)
    rt.set_title(base)
    return "marker cleared: %s" % base
