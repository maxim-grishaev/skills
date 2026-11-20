"""`moe-lead.py usage`: what a thread and everything it spawned used.

Runtime-neutral: the runtime (`thread_tree`, `thread_usage`) knows bb's events; this
module walks, groups, sums, compares with the last snapshot and renders. Exact where
bb keeps the number (threads, turns, requests by trigger, context now), partial or
partial where it does not (bb's token counts), and every partial figure is marked in the output.

The snapshot `S/logs/usage.json` holds, per thread, what the last ask saw, so the next
ask can show what happened since. Fixed texts are templates under templates/usage/.
"""

import concurrent.futures
import datetime
import json
import os

from moelib import templates, waiting
from moelib.runtime import BbError
from moelib.util import Failure, now

WORKERS = 8
TRIGGERS = ("user", "agent", "child-done", "child-failed-or-blocked", "spawn", "other")
BY = ("topic", "notifications", "model")
MAX_GROUP_ROWS = 11  # the default output stays within 20 lines: see render_text


def snapshot_path(root):
    return os.path.join(root, "logs", "usage.json")


def load_snapshot(root):
    try:
        with open(snapshot_path(root)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_snapshot(root, report):
    path = snapshot_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot_of(report), f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def snapshot_of(report):
    return {"asked": report["asked"], "threads": {
        t["id"]: {"turns": t["turns"], "requests": t["requests"], "tokens_total": t["tokens_total"],
                  "session": t["session"], "accumulated": t["accumulated"]}
        for t in report["threads"]}}


# ---------------------------------------------------------------- collecting


def parse_split(text):
    """An ISO time as UTC 'YYYY-MM-DDTHH:MM:SSZ', the form the runtime reports, so strings compare."""
    try:
        moment = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise Failure("--split-at %r is not an ISO time, e.g. 2026-11-16T15:54:00Z" % text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(rt, root_thread, team=None, previous=None, split_at=None, asked=None):
    """The report for `root_thread` and everything under it. `team` is a team.json dict or None;
    `previous` the last snapshot or None; `split_at` an ISO time or None. Pure but for the runtime."""
    tree = rt.thread_tree(root_thread)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        reads = list(pool.map(lambda row: _read(rt, row["id"]), tree))
    names = _team_names(team)
    threads, topics = [], {}
    for row, read in zip(tree, reads):
        threads.append(_thread(row, read, names, topics, root_thread, team, split_at, previous))
    asked = asked or now()
    root = threads[0]
    report = {"root": root_thread, "asked": asked, "split_at": split_at, "named_by_team": team is not None,
              "previous_asked": (previous or {}).get("asked"), "threads": threads,
              "depth": max(t["depth"] for t in threads),
              "archived": sum(1 for t in threads if t["archived"]),
              "unread": [t["id"] for t in threads if t["error"]],
              "lead": {k: root[k] for k in ("id", "name", "turns", "turns_before", "turns_after",
                                            "requests", "triggers", "triggers_before", "triggers_after",
                                            "steered", "context_used", "context_window", "tokens_total")}}
    by_id = {t["id"]: t["name"] for t in threads}
    report["lead"]["child_done"] = _child_done(reads[0].get("requests") or [], by_id, split_at)
    report["total"] = _sum(threads)
    report["deltas"] = _since(threads) if previous else None
    return report


def _child_done(requests, names, split_at):
    """Which children's completion notices woke the root: {name: {"before": n, "after": n}}."""
    out = {}
    for r in requests:
        if r["trigger"] != "child-done":
            continue
        slot = out.setdefault(names.get(r.get("about"), r.get("about") or "?"), {"before": 0, "after": 0})
        slot["before" if split_at and r["at"] and r["at"] < split_at else "after"] += 1
    return out


def _read(rt, thread_id):
    try:
        return rt.thread_usage(thread_id)
    except BbError as e:
        return {"error": str(e)}


def _team_names(team):
    """thread id -> registered name; the Lead is 'lead'."""
    names = {}
    if team:
        for name, entry in (team.get("agents") or {}).items():
            if entry.get("thread"):
                names[entry["thread"]] = name
        if (team.get("lead") or {}).get("thread"):
            names[team["lead"]["thread"]] = "lead"
    return names


def _thread(row, read, names, topics, root_thread, team, split_at, previous):
    """One thread's record: bb's tree row plus its usage, name, topic and deltas."""
    tid, title = row["id"], waiting.strip_marker(row.get("title"))
    if tid in names:
        name, named_by = names[tid], "team"
    elif tid == root_thread:
        name, named_by = "root", "root"
    elif title.startswith("&") and len(title) > 1:
        name, named_by = title[1:], "title"
    else:
        name, named_by = tid, "id"
    if tid == root_thread:
        topic = "-"
    elif "__" in name and named_by != "id":
        topic = name.split("__")[0]
    else:  # standing agents and unnamed threads: the parent's topic, or '-' under the root
        topic = topics.get(row["parent"], "-") if row["parent"] != root_thread else "-"
    topics[tid] = topic
    error = read.get("error")
    turns = read.get("turns") or []
    requests = read.get("requests") or []
    tokens = read.get("tokens") or {}
    context = read.get("context") or {}
    triggers = {k: sum(1 for r in requests if r["trigger"] == k) for k in TRIGGERS}

    def before(at):
        return bool(split_at) and bool(at) and at < split_at

    used = context.get("used")
    record = {
        "id": tid, "name": name, "named_by": named_by, "title": title, "topic": topic,
        "parent": row["parent"], "depth": row["depth"], "status": row.get("status"),
        "provider": row.get("provider"), "model": read.get("model"),
        "notifications": row.get("notifications"), "created": row.get("created"),
        "archived": row.get("archived", False),
        "unregistered": bool(team) and tid not in names and tid != root_thread,
        "error": error,
        "turns": len(turns), "turns_before": sum(1 for t in turns if before(t)) if split_at else None,
        "requests": len(requests), "steered": sum(1 for r in requests if r.get("steer")),
        "triggers": triggers,
        "triggers_before": {k: sum(1 for r in requests if r["trigger"] == k and before(r["at"]))
                            for k in TRIGGERS} if split_at else None,
        "tokens_total": tokens.get("total"), "tokens_output": tokens.get("output"),
        "session": tokens.get("session"),
        "context_used": used, "context_window": context.get("window"), "cost": context.get("cost"),
    }
    record["turns_after"] = None if not split_at else record["turns"] - record["turns_before"]
    record["triggers_after"] = None if not split_at else {
        k: triggers[k] - record["triggers_before"][k] for k in TRIGGERS}
    _delta(record, ((previous or {}).get("threads") or {}).get(tid), bool(previous))
    return record


def _delta(record, prev, have_snapshot):
    """Fill delta fields from the thread's entry in the last snapshot (None: not seen then)."""
    total, session = record["tokens_total"], record["session"]
    prev_acc = (prev or {}).get("accumulated")
    delta = {"turns": record["turns"] - (prev or {}).get("turns", 0) if have_snapshot else None,
             "requests": record["requests"] - (prev or {}).get("requests", 0) if have_snapshot else None,
             "tokens": None, "lower_bound": False, "new": have_snapshot and prev is None}
    if record["error"] and prev:  # unreadable now: keep what the last ask saw
        record.update(turns=prev.get("turns", 0), requests=prev.get("requests", 0))
        record["tokens_total"], record["session"] = prev.get("tokens_total"), prev.get("session")
        record["accumulated"] = prev_acc
        delta.update(turns=0, requests=0)
        record["delta"] = delta
        return
    accumulated = prev_acc if prev_acc is not None else 0
    if total is not None:
        before = (prev or {}).get("tokens_total")
        if prev is None or before is None:
            delta["tokens"] = total
        elif session is not None and session == prev.get("session") and total >= before:
            delta["tokens"] = total - before
        else:  # a new runtime session: the old one's tail is lost, so this is a lower bound
            delta["tokens"], delta["lower_bound"] = total, True
        accumulated += delta["tokens"]
    record["accumulated"] = accumulated if (total is not None or prev_acc is not None) else None
    if delta["turns"] is not None:
        delta["turns"] = max(delta["turns"], 0)
        delta["requests"] = max(delta["requests"], 0)
    record["delta"] = delta


# ---------------------------------------------------------------- sums


def _sum(threads):
    """Totals of a list of thread records."""
    total = {"threads": len(threads), "turns": sum(t["turns"] for t in threads),
             "requests": sum(t["requests"] for t in threads),
             "tokens": sum(t["tokens_total"] or 0 for t in threads),
             "accumulated": sum(t["accumulated"] or 0 for t in threads),
             "delta_turns": None}
    if threads and threads[0]["turns_before"] is not None:
        total["turns_before"] = sum(t["turns_before"] for t in threads)
        total["turns_after"] = sum(t["turns_after"] for t in threads)
    else:
        total["turns_before"] = total["turns_after"] = None
    deltas = [t["delta"] for t in threads]
    if deltas and all(d["turns"] is not None for d in deltas):
        total["delta_turns"] = sum(d["turns"] for d in deltas)
    return total


def _since(threads):
    deltas = [t["delta"] for t in threads]
    return {"turns": sum(d["turns"] or 0 for d in deltas), "requests": sum(d["requests"] or 0 for d in deltas),
            "tokens": sum(d["tokens"] or 0 for d in deltas),
            "lower_bound": any(d["lower_bound"] for d in deltas),
            "new_threads": sum(1 for d in deltas if d["new"]),
            "lead_turns": threads[0]["delta"]["turns"] or 0}


def group_key(thread, by):
    if by == "notifications":
        return thread["notifications"] or "-"
    if by == "model":
        return thread["model"] or "-"
    return thread["topic"]


def groups(report, by):
    """[(key, total)] for every thread under the root, biggest tokens first."""
    members = {}
    for t in report["threads"][1:]:
        members.setdefault(group_key(t, by), []).append(t)
    rows = [(key, _sum(ts)) for key, ts in members.items()]
    return sorted(rows, key=lambda r: (-r[1]["tokens"], -r[1]["turns"], r[0]))


# ---------------------------------------------------------------- output


def tokens_text(n, prefix=""):
    if n is None:
        return "-"
    if n >= 1_000_000:
        return "%s%.1fM" % (prefix, n / 1e6)
    if n >= 1000:
        return "%s%dk" % (prefix, round(n / 1000))
    return "%s%d" % (prefix, n)


def turns_text(total):
    if total.get("turns_before") is None:
        return str(total["turns"])
    return "%d/%d" % (total["turns_before"], total["turns_after"])


def table(rows):
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return [("  ".join(str(c).ljust(w) if i == 0 else str(c).rjust(w)
                       for i, (c, w) in enumerate(zip(r, widths)))).rstrip() for r in rows]


def triggers_text(lead, split_at):
    parts = []
    for k in TRIGGERS:
        n = lead["triggers"][k]
        if n:
            parts.append("%s %d" % (k, n) if not split_at else "%s %d/%d" % (
                k, lead["triggers_before"][k], lead["triggers_after"][k]))
    text = ", ".join(parts) or "none"
    return text + ("; %d steered into a running turn" % lead["steered"] if lead["steered"] else "")


def render_text(report, by="topic", per_thread=False, read_only=None, snapshot_file=None):
    """The default output: at most 20 lines however many threads there are.
    `read_only` is why nothing was saved ('peek', 'thread'), or None when the snapshot was saved."""
    lead, total, split = report["lead"], report["total"], report["split_at"]
    who = "Lead" if lead["name"] == "lead" else "Root"
    lines = [templates.render("usage/header", who=who, thread=report["root"], asked=report["asked"],
                              threads=total["threads"], archived=report["archived"],
                              depth=report["depth"])]
    head = (by, "threads", "turns" + (" before/after" if split else ""), "requests", "tokens (partial)")
    if report["deltas"]:
        head += ("turns since",)
    rows = [head]
    rows.append(_row(lead["name"], _sum(report["threads"][:1]), report))
    shown = groups(report, by)
    if len(shown) > MAX_GROUP_ROWS:
        rest = [t for t in report["threads"][1:] if group_key(t, by) not in {k for k, _ in shown[:MAX_GROUP_ROWS - 1]}]
        shown = shown[:MAX_GROUP_ROWS - 1] + [("(%d more)" % (len({group_key(t, by) for t in rest})), _sum(rest))]
    for key, tot in shown:
        rows.append(_row(key, tot, report))
    rows.append(_row("job total", total, report))
    lines += table(rows)
    lines.append(templates.render(
        "usage/lead", who=who, split=" (before/after %s)" % split if split else "",
        triggers=triggers_text(lead, split),
        context="%s of %s" % (tokens_text(lead["context_used"]), tokens_text(lead["context_window"]))))
    if split and any(v["after"] for v in lead["child_done"].values()):
        lines.append(templates.render("usage/done-after-split", split=split, who=", ".join(
            "%s %d" % (n, v["after"]) for n, v in sorted(lead["child_done"].items()) if v["after"])))
    lines.append(_since_line(report, who, read_only, snapshot_file))
    if report["unread"]:
        lines.append(templates.render("usage/unread", count=len(report["unread"]),
                                      ids=", ".join(report["unread"][:3]) + (", ..." if len(report["unread"]) > 3 else "")))
    lines.append(templates.render("usage/legend"))
    if per_thread:
        lines += [""] + thread_table(report)
    return lines


def _row(label, tot, report):
    cells = [label, tot["threads"], turns_text(tot), tot["requests"],
             tokens_text(tot["tokens"]) if tot["tokens"] else "-"]
    if report["deltas"]:
        cells.append("+%d" % tot["delta_turns"] if tot["delta_turns"] is not None else "-")
    return tuple(cells)


def _since_line(report, who, read_only, snapshot_file):
    d = report["deltas"]
    note = {"peek": " (--peek: nothing saved)", "thread": " (--thread: read-only, nothing saved)"}.get(read_only, "")
    if not d:
        if read_only:
            return templates.render("usage/no-snapshot-read-only", why="--peek" if read_only == "peek" else "--thread")
        return templates.render("usage/first-ask", path=snapshot_file)
    tokens = tokens_text(d["tokens"], "+")
    if d["lower_bound"]:
        tokens = "≥ " + tokens
    return templates.render("usage/since-last", since=report["previous_asked"], turns=d["turns"],
                            who=who, lead_turns=d["lead_turns"], requests=d["requests"], tokens=tokens,
                            new=d["new_threads"], note=note)


def thread_table(report):
    rows = [("thread", "topic", "status", "model", "turns", "requests", "context", "tokens", "cost", "notif", "note")]
    for t in report["threads"]:
        notes = [n for n, on in (("archived", t["archived"]), ("unregistered", t["unregistered"]),
                                 ("unread", bool(t["error"]))) if on]
        cost = t["cost"]
        rows.append((t["name"] if t["named_by"] != "id" else t["id"], t["topic"], t["status"] or "-",
                     t["model"] or "-", turns_text(t), t["requests"], tokens_text(t["context_used"]),
                     tokens_text(t["tokens_total"]),
                     "%s %s" % (cost.get("amount"), cost.get("currency")) if isinstance(cost, dict) else "-",
                     t["notifications"] or "-", ",".join(notes)))
    return table(rows)
