"""The team registry and the message log, in the Lead's storage root S.

`S/logs/team.json`: written only by moe-lead.py. `S/logs/messages.jsonl`:
append-only, both scripts. Identity: an agent finds S from its parent thread
(`<dataDir>/thread-storage/<parent>`), then checks that team.json names that
parent as the Lead.
"""

import json
import os

from moelib.util import Failure, now


def team_path(root):
    return os.path.join(root, "logs", "team.json")


def messages_path(root):
    return os.path.join(root, "logs", "messages.jsonl")


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


def append_message(root, record):
    """Append one line to messages.jsonl. `time` is added. One write call per line."""
    path = messages_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(dict({"time": now()}, **record), ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_messages(root):
    path = messages_path(root)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- the Lead's side


def lead_root(runtime):
    """The Lead's own storage root: this thread's $BB_THREAD_STORAGE."""
    root = runtime.whoami().get("storage")
    if not root:
        raise Failure("no storage root: run this from the Lead's bb thread")
    return root


def require_lead(team, me, root):
    """Refuse unless this thread is the Lead recorded in team.json."""
    lead = (team or {}).get("lead", {}).get("thread")
    if not lead:
        raise Failure("%s has no Lead recorded: run `moe-lead.py setup` first" % team_path(root))
    if me.get("thread") != lead:
        raise Failure("this thread (%s) is not the Lead (%s in %s): moe-lead.py runs only from the "
                      "Lead's thread; agents use moe-agent.py" % (me.get("thread"), lead, team_path(root)))


# ---------------------------------------------------------------- an agent's side


class AgentContext:
    def __init__(self, root, team, me, name):
        self.root = root
        self.team = team
        self.me = me
        self.name = name  # registered name without '&', or None


def agent_context(runtime, override=None, need_name=True):
    """Find S, load the team and identify this thread. Raises Failure naming what it tried."""
    me = runtime.whoami()
    tried = []
    if override:
        root = override
        tried.append("--root %s" % override)
    else:
        root = runtime.team_root(me)
        if not root:
            raise Failure("this thread (%s) has no parent thread, so it cannot find the Lead's storage: "
                          "run it from an agent the Lead spawned, or pass --root <S>" % me.get("thread"))
        tried.append("parent thread %s -> %s" % (me.get("parent"), root))
    team = load_team(root)
    if team is None:
        raise Failure("no team registry %s (tried: %s): pass --root <S> if the Lead's storage is elsewhere"
                      % (team_path(root), "; ".join(tried)))
    lead = team.get("lead", {}).get("thread")
    if not override and lead != me.get("parent"):
        raise Failure("%s names %s as the Lead, but this thread's parent is %s: pass --root <S> if the "
                      "Lead's storage is elsewhere" % (team_path(root), lead, me.get("parent")))
    name = agent_name(team, me.get("thread"))
    if need_name and not name:
        raise Failure("this thread (%s) is not in the team registry %s: only agents spawned with "
                      "`moe-lead.py brief --spawn` are registered" % (me.get("thread"), team_path(root)))
    return AgentContext(root, team, me, name)


def agent_name(team, thread_id):
    for name, entry in (team.get("agents") or {}).items():
        if entry.get("thread") == thread_id:
            return name
    return None


def lookup(team, name):
    """The thread ID of a registered agent. Raises Failure listing the registered names."""
    name = name.lstrip("&")
    agents = team.get("agents") or {}
    if name in agents and agents[name].get("thread"):
        return agents[name]["thread"]
    names = ", ".join("&" + n for n in sorted(agents)) or "none yet"
    hint = " For the Lead use `moe-agent.py tell-lead`." if name.lower() == "lead" else ""
    raise Failure("&%s is not in the team registry. Registered: %s.%s" % (name, names, hint))
