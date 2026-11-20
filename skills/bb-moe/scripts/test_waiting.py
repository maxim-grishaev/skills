"""wait-user and user-answered: the marker on the title and the notification (moelib/waiting.py)."""

import os
import shutil
import tempfile
import unittest

from fake_runtime import FakeRuntime, bb_failure, load_script, make_team, run_cli
from moelib import waiting

agent_cli = load_script("moe-agent.py")
lead_cli = load_script("moe-lead.py")
AGENTS = {"t__build": {"thread": "thr_b", "environment": "env_b", "role": "build", "model": "m", "task": "t"}}


class MarkerTextTest(unittest.TestCase):
    def test_strip_takes_every_leading_marker_and_nothing_else(self):
        for title, plain in (("❓ &a", "&a"), ("❗️ &a", "&a"), ("❗ &a", "&a"), ("❓ ❗️ &a", "&a"),
                             ("❓ 🔔 Ask-user alerts", "🔔 Ask-user alerts"), ("&a ❓", "&a ❓"),
                             ("&a", "&a"), ("", ""), (None, "")):
            self.assertEqual(waiting.strip_marker(title), plain, title)


class WaitingTest(unittest.TestCase):
    """Both entry points, through FakeRuntime: nothing here runs bb."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.base, ignore_errors=True))
        self.root = os.path.join(self.base, "thread-storage", "thr_lead")
        make_team(self.root, agents=AGENTS)
        self.agent_rt = FakeRuntime(thread="thr_b", parent="thr_lead", data_dir=self.base)
        self.agent_rt.me["title"] = "&t__build"
        self.lead_rt = FakeRuntime(thread="thr_lead", data_dir=self.base, storage=self.root)
        self.lead_rt.me["title"] = "🔔 Ask-user alerts"

    def agent(self, *argv, rt=None):
        return run_cli(agent_cli, list(argv), rt or self.agent_rt)

    def lead(self, *argv, rt=None):
        return run_cli(lead_cli, list(argv), rt or self.lead_rt)

    # agent
    def test_a_question_marks_the_title_notifies_and_prints_the_waiting_line(self):
        code, out, err = self.agent("wait-user", "Q2 - model tier")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.agent_rt.me["title"], "❓ &t__build")
        self.assertEqual(self.agent_rt.notified, [("❓ &t__build asks", "Q2 - model tier", "thr_b")])
        self.assertTrue(out.rstrip().endswith("End your turn with: waiting for user on Q2 - model tier"))

    def test_an_action_uses_the_other_marker_and_text(self):
        code, out, _ = self.agent("wait-user", "--act", "API key for the store")
        self.assertEqual(code, 0)
        self.assertEqual(self.agent_rt.me["title"], "❗️ &t__build")
        self.assertEqual(self.agent_rt.notified, [("❗️ &t__build needs you", "API key for the store", "thr_b")])
        self.assertIn("waiting for user on API key for the store", out)

    def test_a_new_wait_replaces_the_marker_and_never_doubles_it(self):
        self.agent("wait-user", "Q1")
        self.agent("wait-user", "--act", "sign in")
        self.assertEqual(self.agent_rt.me["title"], "❗️ &t__build")
        self.agent("wait-user", "Q2")
        self.assertEqual(self.agent_rt.me["title"], "❓ &t__build")
        self.agent("wait-user", "Q3")
        self.assertEqual(self.agent_rt.me["title"], "❓ &t__build")
        self.assertEqual(len(self.agent_rt.notified), 4)  # one push per waiting turn

    def test_the_same_marker_again_does_not_set_the_title_again(self):
        self.agent("wait-user", "Q1")
        self.agent("wait-user", "Q2")
        self.assertEqual([c for c in self.agent_rt.calls if c[0] == "set_title"], [("set_title", "❓ &t__build")])

    def test_clearing_restores_the_title_exactly(self):
        self.agent("wait-user", "Q1")
        code, out, _ = self.agent("user-answered")
        self.assertEqual(code, 0)
        self.assertEqual(self.agent_rt.me["title"], "&t__build")
        self.assertIn("marker cleared", out)
        self.agent("wait-user", "--act", "x")
        self.agent("user-answered")
        self.assertEqual(self.agent_rt.me["title"], "&t__build")

    def test_clearing_without_a_marker_changes_nothing(self):
        code, out, _ = self.agent("user-answered")
        self.assertEqual(code, 0)
        self.assertIn("no marker", out)
        self.assertNotIn("set_title", [c[0] for c in self.agent_rt.calls])

    def test_a_thread_without_a_title_gets_its_name(self):
        self.agent_rt.me["title"] = None
        self.agent("wait-user", "Q1")
        self.assertEqual(self.agent_rt.me["title"], "❓ &t__build")

    def test_the_notification_body_is_cut_to_what_bb_keeps(self):
        self.agent("wait-user", "x" * 300)
        self.assertEqual(len(self.agent_rt.notified[0][1]), 180)

    def test_a_failed_notification_is_a_warning_and_the_line_still_prints(self):
        self.agent_rt.notify_error = bb_failure("not_delivered", "no channel")
        code, out, err = self.agent("wait-user", "Q1")
        self.assertEqual(code, 0)
        self.assertEqual(self.agent_rt.me["title"], "❓ &t__build")
        self.assertIn("notification NOT sent", err)
        self.assertIn("waiting for user on Q1", out)

    def test_a_failed_title_still_notifies(self):
        self.agent_rt.title_error = bb_failure("exit_1", "refused")
        code, out, err = self.agent("wait-user", "Q1")
        self.assertEqual(code, 0)
        self.assertIn("marker NOT set", err)
        self.assertEqual(len(self.agent_rt.notified), 1)
        self.assertIn("waiting for user on Q1", out)

    def test_an_empty_what_is_refused_and_nothing_happens(self):
        code, _, err = self.agent("wait-user", "  ")
        self.assertEqual(code, 2)
        self.assertEqual(self.agent_rt.notified, [])
        self.assertEqual(self.agent_rt.me["title"], "&t__build")

    # Lead
    def test_the_lead_marks_its_own_title_and_signs_as_lead(self):
        code, out, err = self.lead("wait-user", "Q1 - landing")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.lead_rt.me["title"], "❓ 🔔 Ask-user alerts")
        self.assertEqual(self.lead_rt.notified, [("❓ Lead asks", "Q1 - landing", "thr_lead")])
        self.assertIn("waiting for user on Q1 - landing", out)

    def test_the_lead_action_marker_replaces_the_question_and_clears_to_the_original(self):
        self.lead("wait-user", "Q1")
        self.lead("wait-user", "--act", "sign in")
        self.assertEqual(self.lead_rt.me["title"], "❗️ 🔔 Ask-user alerts")
        self.assertEqual(self.lead_rt.notified[-1][0], "❗️ Lead needs you")
        self.lead("user-answered")
        self.assertEqual(self.lead_rt.me["title"], "🔔 Ask-user alerts")

    def test_a_lead_without_a_title_gets_lead(self):
        self.lead_rt.me["title"] = None
        self.lead("wait-user", "Q1")
        self.assertEqual(self.lead_rt.me["title"], "❓ Lead")

    def test_the_lead_verbs_refuse_from_another_thread(self):
        code, _, _ = self.lead("wait-user", "Q1", rt=self.agent_rt)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.agent_rt.notified, [])


if __name__ == "__main__":
    unittest.main()
