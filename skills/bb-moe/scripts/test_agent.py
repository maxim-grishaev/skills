import os
import tempfile
import unittest

from fake_runtime import FakeRuntime, bb_failure, load_script, make_team, run_cli
from moelib import messaging
from moelib import team as teamlib

AGENTS = {
    "t__build": {"thread": "thr_b", "environment": "env_b", "role": "build", "model": "m", "task": "t"},
    "t__qa": {"thread": "thr_q", "environment": "env_b", "role": "qa", "model": "m", "task": "t"},
}
agent_cli = load_script("moe-agent.py")


class AgentCliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = os.path.join(self.dir.name, "thread-storage", "thr_lead")
        make_team(self.root, agents=AGENTS)
        self.rt = FakeRuntime(thread="thr_b", parent="thr_lead", data_dir=self.dir.name)
        self.sleeps = []
        self._sleep = messaging.time.sleep
        messaging.time.sleep = self.sleeps.append  # no real waiting between retries
        self.addCleanup(lambda: setattr(messaging.time, "sleep", self._sleep))

    def run_agent(self, argv, stdin="hello\n"):
        return run_cli(agent_cli, argv, self.rt, stdin)

    def log(self):
        return teamlib.read_messages(self.root)

    # tell
    def test_tell_sends_queued_with_a_sender_line_and_logs_it(self):
        code, out, err = self.run_agent(["tell", "t__qa"], "ready for QA: x\n")
        self.assertEqual(code, 0, err)
        thread, text, mode = self.rt.sent[0]
        self.assertEqual((thread, mode), ("thr_q", "queue"))
        self.assertEqual(text, "From `&t__build`.\n\nready for QA: x")
        self.assertIn("delivered to &t__qa (thr_q): queued", out)
        row = self.log()[0]
        self.assertEqual((row["from"], row["to"], row["toThread"], row["delivery"], row["messageId"]),
                         ("t__build", "t__qa", "thr_q", "queued", "qmsg_1"))
        self.assertEqual((row["kind"], row["topic"], row["first"]), ("tell", "t", "ready for QA: x"))

    def test_tell_now_steers(self):
        self.run_agent(["tell", "t__qa", "--now"])
        self.assertEqual(self.rt.sent[0][2], "steer")

    def test_tell_to_an_unknown_name_lists_the_registered_names_and_sends_nothing(self):
        code, _, err = self.run_agent(["tell", "t__nope"])
        self.assertEqual(code, 2)
        self.assertIn("&t__build, &t__qa", err)
        self.assertEqual(self.rt.sent, [])

    def test_tell_without_a_body_is_refused(self):
        code, _, err = self.run_agent(["tell", "t__qa"], "  \n")
        self.assertEqual(code, 2)
        self.assertIn("empty message", err)
        self.assertEqual(self.rt.sent, [])

    def test_a_thread_outside_the_registry_is_refused(self):
        self.rt = FakeRuntime(thread="thr_stranger", parent="thr_lead", data_dir=self.dir.name)
        code, _, err = self.run_agent(["tell", "t__qa"])
        self.assertEqual(code, 2)
        self.assertIn("not in the team registry", err)

    def test_root_override_works_for_a_thread_with_another_parent(self):
        self.rt = FakeRuntime(thread="thr_b", parent="thr_other", data_dir="/elsewhere")
        code, _, err = self.run_agent(["tell", "t__qa", "--root", self.root])
        self.assertEqual(code, 0, err)

    # tell-lead
    def test_tell_lead_goes_to_the_lead_without_a_thread_argument(self):
        code, out, err = self.run_agent(["tell-lead"], "verdict: ok\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.sent[0][0], "thr_lead")
        self.assertEqual(self.rt.sent[0][1], "From `&t__build`.\n\nverdict: ok")
        self.assertEqual(self.log()[0]["kind"], "tell-lead")
        self.assertNotIn("final answer", out)

    def test_tell_lead_done_marks_it_and_echoes_the_text(self):
        code, out, _ = self.run_agent(["tell-lead", "--done"], "verdict: done\nmore\n")
        self.assertEqual(code, 0)
        self.assertTrue(self.rt.sent[0][1].startswith("From `&t__build`, final answer.\n\n"))
        self.assertTrue(out.rstrip().endswith("verdict: done\nmore"))
        self.assertEqual(self.log()[0]["kind"], "done")

    def test_tell_lead_accepts_8_lines_and_refuses_9(self):
        eight = "\n".join("line %d" % i for i in range(8)) + "\n"
        self.assertEqual(self.run_agent(["tell-lead"], eight)[0], 0)
        nine = "\n".join("line %d" % i for i in range(9)) + "\n"
        code, _, err = self.run_agent(["tell-lead"], nine)
        self.assertEqual(code, 2)
        self.assertIn("9 lines", err)
        self.assertIn("S/reports", err)
        self.assertEqual(len(self.rt.sent), 1)

    def test_tell_lead_refuses_more_than_1200_characters(self):
        self.assertEqual(self.run_agent(["tell-lead"], "x" * 1200 + "\n")[0], 0)
        code, _, err = self.run_agent(["tell-lead"], "x" * 1201 + "\n")
        self.assertEqual(code, 2)
        self.assertIn("1201 characters", err)

    # delivery
    def test_a_failed_answer_is_retried_once_then_exits_1_not_delivered(self):
        self.rt.tell_script = [bb_failure("busy", "try later"), bb_failure("busy", "try later")]
        code, _, err = self.run_agent(["tell-lead"])
        self.assertEqual(code, 1)
        self.assertIn("NOT delivered", err)
        self.assertIn("try later", err)
        self.assertEqual(len(self.rt.sent), 2)  # one try, one retry
        self.assertEqual([r["delivery"] for r in self.log()], ["failed", "failed"])
        self.assertEqual([r["attempt"] for r in self.log()], [1, 2])

    def test_the_retry_can_succeed(self):
        self.rt.tell_script = [bb_failure("busy", "try later")]
        code, out, _ = self.run_agent(["tell", "t__qa"])
        self.assertEqual(code, 0)
        self.assertEqual([r["delivery"] for r in self.log()], ["failed", "queued"])
        self.assertIn("queued", out)

    def test_an_answer_without_sent_or_queued_counts_as_a_failure(self):
        self.rt.tell_script = [{"delivery": "unknown", "id": None}, {"delivery": "unknown", "id": None}]
        code, _, err = self.run_agent(["tell", "t__qa"])
        self.assertEqual(code, 1)
        self.assertIn("NOT delivered", err)

    # who
    def test_who_lists_the_team_and_looks_one_up(self):
        code, out, _ = self.run_agent(["who"])
        self.assertEqual(code, 0)
        self.assertIn("You: &t__build (thr_b)", out)
        self.assertIn("&t__qa: thr_q, qa", out)
        self.assertIn("Lead: thr_lead", out)
        self.assertIn("thr_q", self.run_agent(["who", "t__qa"])[1])
        self.assertIn("thr_lead", self.run_agent(["who", "lead"])[1])
        self.assertEqual(self.run_agent(["who", "t__nope"])[0], 2)


if __name__ == "__main__":
    unittest.main()
