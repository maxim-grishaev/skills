"""Sending a message: size limit, sender line, one retry, a line in messages.jsonl."""

import time

from moelib import team as teamlib
from moelib import templates
from moelib.runtime import BbError

MAX_LINES = 8
MAX_CHARS = 1200
ATTEMPTS = 2  # one try and one retry


class NotDelivered(Exception):
    pass


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
         topic=None, commit=None, mode="queue", sleep=time.sleep):
    """Send `text` to `to_thread` with one retry. Every attempt adds a line to messages.jsonl.
    Returns {"delivery", "id", "attempts"}; raises NotDelivered with bb's error."""
    first = (body if body is not None else text).strip().split("\n", 1)[0][:160]
    topic = topic or topic_of(sender if sender != "lead" else to) or topic_of(to)
    last_error = None
    for attempt in range(1, ATTEMPTS + 1):
        record = {"from": sender, "to": to, "toThread": to_thread, "kind": kind, "topic": topic,
                  "commit": commit, "mode": mode, "attempt": attempt, "first": first}
        try:
            result = runtime.tell(to_thread, text, mode)
            if result.get("delivery") not in ("sent", "queued"):
                raise BbError("bb reported delivery %r, not sent or queued" % result.get("delivery"),
                              "bad_delivery")
        except BbError as e:
            last_error = e
            teamlib.append_message(root, dict(record, delivery="failed", error=str(e)))
            if attempt < ATTEMPTS:
                sleep(1.0)
            continue
        teamlib.append_message(root, dict(record, delivery=result["delivery"], messageId=result.get("id")))
        return {"delivery": result["delivery"], "id": result.get("id"), "attempts": attempt}
    raise NotDelivered("NOT delivered to %s (%s) after %d tries: %s" % (to, to_thread, ATTEMPTS, last_error))
