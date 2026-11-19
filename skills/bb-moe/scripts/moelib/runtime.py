"""The only code that runs bb (ADR 0001, ADR 0002).

`BbRuntime` is the one implementation of a small interface. Every method returns
plain dicts, lists or strings, so no bb JSON shape leaks past this file. A second
runtime is another class with the same methods; the tests use `FakeRuntime`
(scripts/fake_runtime.py).

bb is run as $BB_CLI (the daemon-managed binary) when set, else as `bb` from PATH.
Every call asks for `--json` and checks the answer: a non-zero exit or
`{"ok": false, "error": {code, message, hint}}` on stdout raises `BbError`.
"""

import json
import os
import re
import subprocess


class BbError(Exception):
    """bb refused or failed. `code` is bb's error code, or `exit_<n>` / `not_found`."""

    def __init__(self, message, code="error", hint=None, exit_code=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.exit_code = exit_code

    def __str__(self):
        text = "%s: %s" % (self.code, self.message)
        return text + (" (hint: %s)" % self.hint if self.hint else "")


DEFAULT_CLI = "bb"


class BbRuntime:
    def __init__(self, cli=None):
        self.cli = cli or os.environ.get("BB_CLI") or DEFAULT_CLI

    # ---------------------------------------------------------------- plumbing

    def argv(self, args):
        return [self.cli] + list(args)

    def _run(self, args, stdin=None, json_flag=True, ok_exit=(0,)):
        """Run bb; return (exit code, stdout). Raise BbError on failure."""
        return self._exec(self.argv(list(args) + (["--json"] if json_flag else [])), stdin, ok_exit)

    def _exec(self, cmd, stdin=None, ok_exit=(0,)):
        try:
            feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
            p = subprocess.run(cmd, capture_output=True, text=True, **feed)
        except FileNotFoundError:
            raise BbError("command not found: %s" % self.cli, "not_found")
        out = p.stdout
        if p.returncode in ok_exit and p.returncode != 0:
            return p.returncode, out
        envelope = _parse(out)
        if isinstance(envelope, dict) and envelope.get("ok") is False:
            err = envelope.get("error") or {}
            raise BbError(err.get("message") or "bb answered ok: false",
                          err.get("code") or "error", err.get("hint"), p.returncode)
        if p.returncode != 0:
            detail = (p.stderr or out).strip()
            raise BbError(detail or "bb exited %d" % p.returncode,
                          "exit_%d" % p.returncode, None, p.returncode)
        return 0, out

    def _json(self, args, stdin=None):
        _, out = self._run(args, stdin)
        data = _parse(out)
        return data if data is not None else {}

    # ---------------------------------------------------------------- identity

    def whoami(self):
        """This thread: id, parent, project, environment, data dir, own storage path."""
        data = self._json(["status"])
        thread = data.get("thread") or {}
        env = (thread.get("environment") or {}).get("display") or {}
        data_dir = data.get("dataDir")
        thread_id = os.environ.get("BB_THREAD_ID") or thread.get("id")
        storage = os.environ.get("BB_THREAD_STORAGE")
        if not storage and data_dir and thread_id:
            storage = os.path.join(data_dir, "thread-storage", thread_id)
        return {
            "thread": thread_id,
            "parent": thread.get("parentThreadId"),
            "project": (data.get("project") or {}).get("id") or os.environ.get("BB_PROJECT_ID"),
            "environment": env.get("id") or os.environ.get("BB_ENVIRONMENT_ID"),
            "data_dir": data_dir,
            "storage": storage,
            "children": [{"id": c.get("id"), "status": c.get("status"), "title": c.get("title")}
                         for c in data.get("childThreads") or []],
        }

    def team_root(self, me=None):
        """The storage root S of this thread's parent (the Lead), or None without a parent.
        Pass the `whoami()` answer you already hold to save a bb call."""
        me = me or self.whoami()
        if not me["parent"] or not me["data_dir"]:
            return None
        return os.path.join(me["data_dir"], "thread-storage", me["parent"])

    def list_children(self):
        return self.whoami()["children"]

    def set_title(self, title):
        self._run(["thread", "update", "--self", "--title", title])

    # ---------------------------------------------------------------- threads

    def show(self, thread_id):
        """A thread: {"id", "project", "environment_id", "provider", "status",
        "environment": None or {"id", "path", "branch", "is_git_repo"}}."""
        data = self._json(["thread", "show", thread_id])
        thread = data.get("thread") or {}
        env = data.get("environment")
        return {
            "id": thread.get("id"),
            "project": thread.get("projectId"),
            "environment_id": thread.get("environmentId") or (env or {}).get("id"),
            "provider": thread.get("providerId"),
            "status": thread.get("status"),
            "environment": None if not env else {
                "id": env.get("id"), "path": env.get("path"), "branch": env.get("branchName"),
                "is_git_repo": bool(env.get("isGitRepo")),
            },
        }

    def environment_path(self, environment_id):
        data = self._json(["environment", "show", environment_id])
        return (data.get("environment", data) or {}).get("path")

    def _spawn_argv(self, spec):
        """The bb command for a spawn. `spec` keys: project, title, provider, model,
        prompt_file; optional: reasoning_level (default high), parent_notifications
        (default stuck), environment, new_worktree_base, permission_mode."""
        args = ["thread", "spawn", "--project", spec["project"], "--parent-self",
                "--title", spec["title"], "--provider", spec["provider"],
                "--model", spec["model"],
                "--reasoning-level", spec.get("reasoning_level", "high"),
                "--parent-notifications", spec.get("parent_notifications", "stuck")]
        if spec.get("environment"):
            args += ["--environment", spec["environment"]]
        if spec.get("new_worktree_base"):
            args += ["--new-environment", "worktree", "--base-branch", spec["new_worktree_base"]]
        if spec.get("permission_mode"):
            args += ["--permission-mode", spec["permission_mode"]]
        args += ["--prompt-file", spec["prompt_file"], "--json"]
        return self.argv(args)

    def describe_spawn(self, spec):
        """The spawn as one printable shell command, for a dry run."""
        return " ".join(_shell_quote(a) for a in self._spawn_argv(spec))

    def spawn(self, spec):
        """Spawn a thread. Returns {"thread": id or None, "environment": id or None, "raw": stdout}.
        Raises BbError when bb refuses. A None thread means bb exited 0 without an ID:
        the thread may exist."""
        _, out = self._exec(self._spawn_argv(spec))
        envelope = _parse(out)
        data = envelope if isinstance(envelope, dict) else {}
        thread = data.get("thread", data)
        return {
            "thread": thread.get("id"),
            "environment": thread.get("environmentId") or (data.get("environment") or {}).get("id"),
            "raw": out,
        }

    def tell(self, thread_id, text, mode="queue", compact_first=False):
        """Send `text` (stdin) to a thread. mode: queue (waits until it is free) or
        steer (the active turn). Returns {"delivery": "sent|queued", "id": queued-message id or None}."""
        args = ["thread", "tell", thread_id, "--message-file", "-"]
        if mode != "steer":
            args += ["--mode", mode]
        if compact_first:
            args.append("--compact-first")
        data = self._json(args, stdin=text)
        if not isinstance(data, dict):
            data = {}
        queued = data.get("queuedMessage") or {}
        return {"delivery": data.get("delivery") or "unknown", "id": queued.get("id")}

    def output(self, thread_id):
        data = self._json(["thread", "output", thread_id])
        return data.get("output", "") if isinstance(data, dict) else ""

    def log(self, thread_id, everything=False):
        """The thread's event log as bb's readable text."""
        args = ["thread", "log", thread_id] + (["--all"] if everything else [])
        _, out = self._run(args, json_flag=False)
        return out

    def wait(self, thread_id, timeout="20m"):
        """Block until the thread is idle. Returns {"matched": bool, "exit": 0|2|4|..}:
        exit 2 is a timeout, 4 a thread in error with nothing queued to recover it [bb docs]."""
        code, out = self._run(["thread", "wait", thread_id, "--timeout", timeout],
                              ok_exit=(0, 2, 4))
        data = _parse(out)
        matched = bool(data.get("matched")) if isinstance(data, dict) else code == 0
        return {"matched": matched, "exit": code}

    def retry(self, thread_id):
        self._run(["thread", "retry", thread_id])

    def compact(self, thread_id):
        self._run(["thread", "compact", thread_id])

    def stop(self, thread_id):
        self._run(["thread", "stop", thread_id])

    def context_self(self):
        """{"used_tokens", "window"} for this thread; a key bb leaves out is absent."""
        data = self._json(["thread", "context", "--self"])
        usage = data.get("usage") or {} if isinstance(data, dict) else {}
        out = {}
        if "usedTokens" in usage:
            out["used_tokens"] = usage["usedTokens"]
        if "modelContextWindow" in usage:
            out["window"] = usage["modelContextWindow"]
        return out

    # ---------------------------------------------------------------- providers

    def providers(self):
        """[{"id", "available"}] for every provider bb lists."""
        data = self._json(["provider", "list"])
        return [{"id": p.get("id"), "available": bool(p.get("available"))}
                for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    def default_provider(self):
        data = self._json(["settings", "show"])
        return (data.get("generalSettings") or {}).get("defaultProviderId")

    def models(self, provider, project):
        """The provider's models: [{"id", "name", "description", "is_default", "efforts"}];
        "efforts" lists the reasoning-effort names the model supports."""
        data = self._json(["provider", "models", provider, "--project", project])
        return [{"id": m.get("id"), "name": m.get("displayName"), "description": m.get("description"),
                 "is_default": bool(m.get("isDefault")), "efforts": _effort_names(m)}
                for m in data if isinstance(m, dict)] if isinstance(data, list) else []


def _effort_names(model):
    """Effort names from bb's supportedReasoningEfforts: objects with `reasoningEffort`, or plain strings."""
    names = []
    for e in model.get("supportedReasoningEfforts") or []:
        name = e.get("reasoningEffort") if isinstance(e, dict) else e
        if name:
            names.append(name)
    return names


def _shell_quote(s):
    return s if re.match(r"^[A-Za-z0-9_./:=@%+-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


def _parse(text):
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None
