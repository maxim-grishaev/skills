"""BbRuntime against a stand-in executable, and the interface parity with FakeRuntime."""

import inspect
import json
import os
import stat
import tempfile
import unittest

from fake_runtime import FakeRuntime
from moelib.runtime import DEFAULT_CLI, BbError, BbRuntime

# The stand-in CLI: prints $STANDIN_OUT, writes its argv and stdin to $STANDIN_LOG, exits $STANDIN_EXIT.
STANDIN = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STANDIN_LOG"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read() if not sys.stdin.isatty() else ""}) + "\\n")
sys.stdout.write(os.environ.get("STANDIN_OUT", ""))
sys.stderr.write(os.environ.get("STANDIN_ERR", ""))
sys.exit(int(os.environ.get("STANDIN_EXIT", "0")))
"""


class StandInTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cli = os.path.join(self.dir.name, "standin")
        with open(self.cli, "w") as f:
            f.write(STANDIN)
        os.chmod(self.cli, os.stat(self.cli).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.dir.name, "calls.jsonl")
        self.env = {"STANDIN_LOG": self.log}
        saved = dict(os.environ)
        os.environ.update(self.env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        self.rt = BbRuntime(cli=self.cli)

    def answer(self, out, exit_code=0, err=""):
        os.environ["STANDIN_OUT"] = out if isinstance(out, str) else json.dumps(out)
        os.environ["STANDIN_EXIT"] = str(exit_code)
        os.environ["STANDIN_ERR"] = err

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def test_bb_cli_is_preferred_over_bare_bb(self):
        os.environ["BB_CLI"] = "/path/to/daemon-bb"
        self.assertEqual(BbRuntime().cli, "/path/to/daemon-bb")
        del os.environ["BB_CLI"]
        self.assertEqual(BbRuntime().cli, DEFAULT_CLI)

    def test_ok_false_envelope_raises_with_code_and_hint(self):
        self.answer({"ok": False, "error": {"code": "thread_not_found", "message": "no thread", "hint": "list"}},
                    exit_code=1)
        with self.assertRaises(BbError) as c:
            self.rt.show("thr_x")
        self.assertEqual(c.exception.code, "thread_not_found")
        self.assertIn("no thread", str(c.exception))
        self.assertIn("list", str(c.exception))

    def test_ok_false_with_exit_zero_still_raises(self):
        self.answer({"ok": False, "error": {"code": "x", "message": "refused"}})
        with self.assertRaises(BbError):
            self.rt.tell("thr_x", "hi")

    def test_nonzero_exit_without_envelope_raises(self):
        self.answer("", exit_code=3, err="boom")
        with self.assertRaises(BbError) as c:
            self.rt.stop("thr_x")
        self.assertEqual(c.exception.code, "exit_3")
        self.assertIn("boom", str(c.exception))

    def test_missing_executable_raises(self):
        with self.assertRaises(BbError) as c:
            BbRuntime(cli=os.path.join(self.dir.name, "nope")).stop("thr_x")
        self.assertEqual(c.exception.code, "not_found")

    def test_tell_sends_text_on_stdin_in_queue_mode(self):
        self.answer({"ok": True, "delivery": "queued", "queuedMessage": {"id": "qmsg_1"}})
        self.assertEqual(self.rt.tell("thr_x", "hello\nworld"), {"delivery": "queued", "id": "qmsg_1"})
        call = self.calls()[0]
        self.assertEqual(call["argv"], ["thread", "tell", "thr_x", "--message-file", "-", "--mode", "queue", "--json"])
        self.assertEqual(call["stdin"], "hello\nworld")

    def test_tell_steer_has_no_mode_flag_and_compact_first_is_passed(self):
        self.answer({"ok": True, "delivery": "sent"})
        self.rt.tell("thr_x", "hi", mode="steer", compact_first=True)
        argv = self.calls()[0]["argv"]
        self.assertNotIn("--mode", argv)
        self.assertIn("--compact-first", argv)

    def test_describe_spawn_carries_stuck_and_permission_mode(self):
        spec = {"project": "proj_1", "title": "&a", "provider": "p", "model": "m", "prompt_file": "/f.md",
                "new_worktree_base": "abc123", "permission_mode": "accept-edits"}
        joined = self.rt.describe_spawn(spec)
        self.assertTrue(joined.startswith(self.cli + " thread spawn"))
        for part in ("--parent-self", "--parent-notifications stuck", "--reasoning-level high",
                     "--new-environment worktree --base-branch abc123", "--permission-mode accept-edits",
                     "--prompt-file /f.md"):
            self.assertIn(part, joined)
        self.assertNotIn("--permission-mode", self.rt.describe_spawn(dict(spec, permission_mode=None)))

    def test_spawn_returns_ids_from_a_bare_thread_or_a_wrapper(self):
        spec = {"project": "p", "title": "t", "provider": "p", "model": "m", "prompt_file": "/f", "environment": "e"}
        self.answer({"id": "thr_a", "environmentId": "env_a"})
        self.assertEqual(self.rt.spawn(spec)["thread"], "thr_a")
        self.answer({"thread": {"id": "thr_b"}, "environment": {"id": "env_b"}})
        got = self.rt.spawn(spec)
        self.assertEqual((got["thread"], got["environment"]), ("thr_b", "env_b"))
        self.answer({})
        self.assertIsNone(self.rt.spawn(spec)["thread"])

    def test_show_returns_plain_names_not_bb_keys(self):
        self.answer({"thread": {"id": "thr_a", "projectId": "proj_1", "environmentId": "env_a",
                                "providerId": "claude-code", "status": "idle"},
                     "environment": {"id": "env_a", "path": "/w", "branchName": "b", "isGitRepo": True}})
        self.assertEqual(self.rt.show("thr_a"), {
            "id": "thr_a", "project": "proj_1", "environment_id": "env_a", "provider": "claude-code",
            "status": "idle", "environment": {"id": "env_a", "path": "/w", "branch": "b", "is_git_repo": True}})
        self.answer({"thread": {"id": "thr_b"}, "environment": None})
        shown = self.rt.show("thr_b")
        self.assertIsNone(shown["environment"])
        self.assertIsNone(shown["environment_id"])

    def test_team_root_uses_the_identity_it_is_given(self):
        self.answer({"dataDir": "/d", "thread": {"id": "thr_c", "parentThreadId": "thr_p"}})
        me = self.rt.whoami()
        before = len(self.calls())
        self.assertEqual(self.rt.team_root(me), "/d/thread-storage/thr_p")
        self.assertEqual(len(self.calls()), before)  # no second bb call

    def test_wait_maps_timeout_and_error_exits_without_raising(self):
        self.answer("", exit_code=2)
        self.assertEqual(self.rt.wait("thr_x"), {"matched": False, "exit": 2})
        self.answer("", exit_code=4)
        self.assertEqual(self.rt.wait("thr_x")["exit"], 4)
        self.answer({"matched": True}, exit_code=0)
        self.assertEqual(self.rt.wait("thr_x"), {"matched": True, "exit": 0})

    def test_whoami_and_team_root_derive_from_the_parent(self):
        os.environ.pop("BB_THREAD_STORAGE", None)
        os.environ.pop("BB_THREAD_ID", None)
        self.answer({"dataDir": "/d", "project": {"id": "proj_1"},
                     "thread": {"id": "thr_c", "parentThreadId": "thr_p", "environment": {"display": {"id": "env_c"}}},
                     "childThreads": [{"id": "thr_k", "status": "idle", "title": "&k"}]})
        me = self.rt.whoami()
        self.assertEqual((me["thread"], me["parent"], me["project"], me["environment"]),
                         ("thr_c", "thr_p", "proj_1", "env_c"))
        self.assertEqual(me["storage"], "/d/thread-storage/thr_c")
        self.assertEqual(self.rt.team_root(), "/d/thread-storage/thr_p")
        self.assertEqual(self.rt.list_children(), [{"id": "thr_k", "status": "idle", "title": "&k"}])

    def test_team_root_is_none_without_a_parent(self):
        self.answer({"dataDir": "/d", "thread": {"id": "thr_c", "parentThreadId": None}})
        self.assertIsNone(self.rt.team_root())

    def test_read_methods_return_plain_data(self):
        self.answer([{"id": "claude-code", "available": True, "extra": 1}, {"id": "codex", "available": False}])
        self.assertEqual(self.rt.providers(), [{"id": "claude-code", "available": True},
                                               {"id": "codex", "available": False}])
        self.answer({"generalSettings": {"defaultProviderId": "claude-code"}})
        self.assertEqual(self.rt.default_provider(), "claude-code")
        self.answer({"output": "final text"})
        self.assertEqual(self.rt.output("thr_x"), "final text")
        self.answer({"usage": {"usedTokens": 10, "modelContextWindow": 100}})
        self.assertEqual(self.rt.context_self(), {"used_tokens": 10, "window": 100})
        self.answer({"environment": {"path": "/w"}})
        self.assertEqual(self.rt.environment_path("env_x"), "/w")
        self.answer([{"id": "m1"}])
        self.answer([{"id": "m1", "displayName": "Model One", "description": "fast", "other": 1}])
        self.assertEqual(self.rt.models("claude-code", "proj_1"),
                         [{"id": "m1", "name": "Model One", "description": "fast", "is_default": False, "efforts": []}])


class InterfaceParityTest(unittest.TestCase):
    """FakeRuntime is the interface's second implementation: same public methods, same parameters."""

    def public(self, cls):
        return {n: [p for p in inspect.signature(f).parameters]
                for n, f in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}

    def test_fake_runtime_has_every_public_method_of_the_real_one(self):
        real, fake = self.public(BbRuntime), self.public(FakeRuntime)
        self.assertEqual(sorted(set(real) - {"argv"}), sorted(set(fake)))
        for name in fake:
            self.assertEqual(real[name], fake[name], name)

    def test_whole_interface_of_the_architecture_is_present(self):
        wanted = {"whoami", "team_root", "spawn", "tell", "show", "output", "log", "list_children", "wait",
                  "retry", "compact", "stop", "set_title", "context_self", "providers", "default_provider",
                  "models", "environment_path"}
        self.assertTrue(wanted <= set(self.public(BbRuntime)))


if __name__ == "__main__":
    unittest.main()
