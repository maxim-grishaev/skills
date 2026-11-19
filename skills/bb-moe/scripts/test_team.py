import json
import os
import tempfile
import unittest

from fake_runtime import FakeRuntime, make_team
from moelib import team as teamlib
from moelib.util import Failure

AGENTS = {
    "t__build": {"thread": "thr_b", "environment": "env_b", "role": "build"},
    "t__qa": {"thread": "thr_q", "environment": "env_b", "role": "qa"},
}


class TeamFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = os.path.join(self.dir.name, "S")

    def test_save_and_load_round_trip(self):
        teamlib.save_team(self.root, {"lead": {"thread": "thr_lead"}, "agents": {}})
        self.assertEqual(teamlib.load_team(self.root)["lead"]["thread"], "thr_lead")
        self.assertIsNone(teamlib.load_team(os.path.join(self.dir.name, "none")))

    def test_messages_are_appended_one_json_line_each(self):
        teamlib.append_message(self.root, {"from": "a", "to": "b", "delivery": "queued"})
        teamlib.append_message(self.root, {"from": "b", "to": "a", "delivery": "failed"})
        rows = teamlib.read_messages(self.root)
        self.assertEqual([r["delivery"] for r in rows], ["queued", "failed"])
        self.assertTrue(all("time" in r for r in rows))
        with open(teamlib.messages_path(self.root)) as f:
            self.assertEqual(len(f.read().splitlines()), 2)

    def test_lookup_known_and_unknown(self):
        team = {"agents": AGENTS}
        self.assertEqual(teamlib.lookup(team, "t__qa"), "thr_q")
        self.assertEqual(teamlib.lookup(team, "&t__qa"), "thr_q")
        with self.assertRaises(Failure) as c:
            teamlib.lookup(team, "t__nope")
        self.assertIn("&t__build, &t__qa", str(c.exception))

    def test_lookup_of_the_lead_points_to_tell_lead(self):
        with self.assertRaises(Failure) as c:
            teamlib.lookup({"agents": AGENTS}, "Lead")
        self.assertIn("tell-lead", str(c.exception))


class AgentContextTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = self.dir.name
        self.root = os.path.join(self.data, "thread-storage", "thr_lead")
        make_team(self.root, agents=AGENTS)

    def rt(self, thread="thr_b", parent="thr_lead"):
        return FakeRuntime(thread=thread, parent=parent, data_dir=self.data)

    def test_derives_root_from_parent_and_finds_own_name(self):
        ctx = teamlib.agent_context(self.rt())
        self.assertEqual((ctx.root, ctx.name), (self.root, "t__build"))

    def test_root_override_skips_the_parent_check(self):
        ctx = teamlib.agent_context(self.rt(parent="thr_other"), override=self.root)
        self.assertEqual(ctx.name, "t__build")

    def test_parent_that_is_not_the_lead_is_refused_naming_both(self):
        make_team(os.path.join(self.data, "thread-storage", "thr_other"), lead="thr_somebody", agents=AGENTS)
        with self.assertRaises(Failure) as c:
            teamlib.agent_context(self.rt(parent="thr_other"))
        self.assertIn("thr_somebody", str(c.exception))
        self.assertIn("thr_other", str(c.exception))

    def test_missing_registry_names_the_path_it_tried(self):
        with self.assertRaises(Failure) as c:
            teamlib.agent_context(self.rt(parent="thr_nowhere"))
        self.assertIn(os.path.join("thr_nowhere", "logs", "team.json"), str(c.exception))

    def test_unregistered_thread_is_refused_naming_the_registry(self):
        with self.assertRaises(Failure) as c:
            teamlib.agent_context(self.rt(thread="thr_stranger"))
        self.assertIn("not in the team registry", str(c.exception))
        self.assertIn("team.json", str(c.exception))
        self.assertIsNone(teamlib.agent_context(self.rt(thread="thr_stranger"), need_name=False).name)

    def test_no_parent_is_refused(self):
        with self.assertRaises(Failure) as c:
            teamlib.agent_context(self.rt(parent=None))
        self.assertIn("no parent", str(c.exception))


if __name__ == "__main__":
    unittest.main()
