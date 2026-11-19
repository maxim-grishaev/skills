"""FakeRuntime: the second implementation of the runtime interface (moelib/runtime.py).

It records every call and answers from fields the test sets. It never runs a
process. `make_team` builds a scratch Lead's storage root for the CLIs under test.
"""

import json
import os

from moelib.runtime import BbError


class FakeRuntime:
    def __init__(self, thread="thr_lead", parent=None, project="proj_1", environment="env_lead",
                 data_dir="/fake/data", storage=None):
        self.me = {"thread": thread, "parent": parent, "project": project, "environment": environment,
                   "data_dir": data_dir,
                   "storage": storage or os.path.join(data_dir, "thread-storage", thread),
                   "children": []}
        self.calls = []
        self.sent = []  # (thread id, text, mode)
        self.tell_script = []  # answers for tell(), in order: a dict, or an Exception to raise
        self.shown = {"id": thread, "project": project, "environment_id": environment,
                      "provider": "claude-code", "status": "active",
                      "environment": {"id": environment, "path": "/work/lead", "branch": "work",
                                      "is_git_repo": True}}
        self.env_paths = {}
        self.spawn_error = None
        self.spawn_without_id = False
        self.spawn_without_environment = False  # bb prints no environment ID at spawn (new worktree)
        self.new_environment_visible = True  # does show() find it afterwards
        self.spawned = []
        self.shown_threads = {}  # spawned thread -> its environment ID
        self.default = "claude-code"
        self.provider_list = [{"id": "claude-code", "available": True}]
        self.model_list = []
        self.wait_result = {"matched": True, "exit": 0}
        self.context = {}

    def _record(self, name, *args):
        self.calls.append((name,) + args)

    # identity
    def whoami(self):
        self._record("whoami")
        return dict(self.me)

    def team_root(self, me=None):
        self._record("team_root")
        if not self.me["parent"] or not self.me["data_dir"]:
            return None
        return os.path.join(self.me["data_dir"], "thread-storage", self.me["parent"])

    def list_children(self):
        self._record("list_children")
        return list(self.me["children"])

    def set_title(self, title):
        self._record("set_title", title)

    # threads
    def show(self, thread_id):
        self._record("show", thread_id)
        if thread_id in self.shown_threads:
            env = self.shown_threads[thread_id]
            return {"id": thread_id, "project": self.me["project"], "environment_id": env,
                    "provider": "claude-code", "status": "idle",
                    "environment": {"id": env, "path": None, "branch": None, "is_git_repo": True}
                    if env else None}
        return json.loads(json.dumps(self.shown))

    def environment_path(self, environment_id):
        self._record("environment_path", environment_id)
        return self.env_paths.get(environment_id)

    def describe_spawn(self, spec):
        args = ["fake-runtime", "spawn"]
        for key in sorted(spec):
            args += ["--" + key.replace("_", "-"), str(spec[key])]
        return " ".join(args)

    def spawn(self, spec):
        self._record("spawn", dict(spec))
        if self.spawn_error:
            raise self.spawn_error
        n = len(self.spawned) + 1
        self.spawned.append(dict(spec))
        if self.spawn_without_id:
            return {"thread": None, "environment": None, "raw": "{}"}
        env = spec.get("environment") or "env_new%d" % n
        self.shown_threads["thr_new%d" % n] = env if self.new_environment_visible else None
        return {"thread": "thr_new%d" % n, "environment": None if self.spawn_without_environment else env,
                "raw": "{}"}

    def tell(self, thread_id, text, mode="queue", compact_first=False):
        self._record("tell", thread_id, mode)
        self.sent.append((thread_id, text, mode))
        if self.tell_script:
            answer = self.tell_script.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {"delivery": "queued", "id": "qmsg_%d" % len(self.sent)}

    def output(self, thread_id):
        self._record("output", thread_id)
        return ""

    def log(self, thread_id, everything=False):
        self._record("log", thread_id, everything)
        return ""

    def wait(self, thread_id, timeout="20m"):
        self._record("wait", thread_id, timeout)
        return dict(self.wait_result)

    def retry(self, thread_id):
        self._record("retry", thread_id)

    def compact(self, thread_id):
        self._record("compact", thread_id)

    def stop(self, thread_id):
        self._record("stop", thread_id)

    def context_self(self):
        self._record("context_self")
        return dict(self.context)

    # providers
    def providers(self):
        self._record("providers")
        return list(self.provider_list)

    def default_provider(self):
        self._record("default_provider")
        return self.default

    def models(self, provider, project):
        self._record("models", provider, project)
        return list(self.model_list)


def make_git_repo(path):
    """A real git repo with one commit; returns the commit's SHA."""
    import subprocess
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "-C", path, "init", "-q"], check=True)
    subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "--allow-empty", "-m", "first"], check=True)
    return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def bb_failure(code="thread_not_found", message="no such thread"):
    return BbError(message, code)


def make_team(root, lead="thr_lead", agents=None, weight="full", worktree="/work/lead"):
    """Write S/logs/team.json under `root` and return the team dict."""
    from moelib import team as teamlib
    team = {
        "lead": {"thread": lead, "project": "proj_1", "environment": "env_lead",
                 "worktree": worktree, "branch": "work", "isGitRepo": True},
        "tiers": {"provider": "claude-code", "stronger": "model-strong", "mid": "model-mid"},
        "weight": weight,
        "agents": agents or {},
    }
    teamlib.save_team(root, team)
    return team


# ---------------------------------------------------------------- running the CLIs in a test

def load_script(filename):
    """Import scripts/<filename> (the entry points have a hyphen in their names)."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(module, argv, runtime, stdin=""):
    """Run module.main(argv) with `runtime`, a piped stdin and captured output.
    Returns (exit code, stdout, stderr)."""
    import contextlib
    import io
    import sys
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                result = module.main(argv, runtime=runtime)
                code = result or 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()
