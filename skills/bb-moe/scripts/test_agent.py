import os
import tempfile
import unittest

from fake_runtime import FakeRuntime, bb_failure, load_script, make_git_repo, make_team, run_cli
from moelib import messaging
from moelib import team as teamlib
from moelib import templates

AGENTS = {
    "t__build": {"thread": "thr_b", "environment": "env_b", "role": "build", "model": "m", "task": "t"},
    "t__qa": {"thread": "thr_q", "environment": "env_b", "role": "qa", "model": "m", "task": "t"},
    "t__reviewer": {"thread": "thr_r", "environment": "env_b", "role": "reviewer", "model": "m", "task": "t"},
    "butler": {"thread": "thr_butler", "environment": "env_lead", "role": "butler", "model": "m", "task": "t"},
    "main__qa": {"thread": "thr_mqa", "environment": "env_lead", "role": "main-qa", "model": "m", "task": "t"},
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

    def test_an_exit_0_answer_without_sent_or_queued_is_unconfirmed_and_not_resent(self):
        self.rt.tell_script = [{"delivery": "unknown", "id": None}]
        code, _, err = self.run_agent(["tell", "t__qa"])
        self.assertEqual(code, 1)
        self.assertIn("UNCONFIRMED", err)
        self.assertNotIn("NOT delivered", err)
        self.assertEqual(len(self.rt.sent), 1)  # bb may have queued it: no second send
        self.assertEqual([r["delivery"] for r in self.log()], ["unconfirmed"])

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


class ChainRuntime(FakeRuntime):
    """FakeRuntime that records compact_first and answers wait() from a list."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.compact_first_flags = []
        self.wait_script = []  # answers for wait(), in order

    def tell(self, thread_id, text, mode="queue", compact_first=False):
        self.compact_first_flags.append(compact_first)
        return super().tell(thread_id, text, mode, compact_first)

    def wait(self, thread_id, timeout="20m"):
        self._record("wait", thread_id, timeout)
        return self.wait_script.pop(0) if self.wait_script else {"matched": True, "exit": 0}


class ChainTest(unittest.TestCase):
    """`tell --kind`: the review chain's messages, from templates/chain and templates/lead."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = os.path.join(self.dir.name, "thread-storage", "thr_lead")
        make_team(self.root, agents=dict(AGENTS, **{
            "t__review-skeptic": {"thread": "thr_s", "environment": "env_b", "role": "review-skeptic",
                                  "model": "m", "task": "t"}}))
        self.repo = os.path.join(self.dir.name, "repo")
        self.sha = make_git_repo(self.repo)
        self.base = self.sha
        self.old_cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(lambda: os.chdir(self.old_cwd))
        os.makedirs(os.path.join(self.root, "reports"))
        with open(os.path.join(self.root, "reports", "t__review-01.md"), "w") as f:
            f.write("findings\n")
        self.rt = ChainRuntime(thread="thr_b", parent="thr_lead", data_dir=self.dir.name)
        self._sleep = messaging.time.sleep
        messaging.time.sleep = lambda s: None
        self.addCleanup(lambda: setattr(messaging.time, "sleep", self._sleep))

    def as_thread(self, thread):
        self.rt = ChainRuntime(thread=thread, parent="thr_lead", data_dir=self.dir.name)

    def run_agent(self, argv, stdin=""):
        return run_cli(agent_cli, argv, self.rt, stdin)

    def log(self):
        return teamlib.read_messages(self.root)

    def sent_text(self, n=0):
        return self.rt.sent[n][1].split("\n\n", 1)[1]  # without the sender line

    # the texts review-chain.md has today, field for field
    def test_ready_for_qa_has_two_wordings(self):
        code, _, err = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "the thing"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sent_text(), "t ready for QA: the thing")
        code, _, err = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "the thing",
                                       "--commit", "HEAD"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sent_text(1), "t ready for QA: the thing, commit " + self.sha)

    def test_qa_passed_reads_as_in_the_chain_doc(self):
        self.as_thread("thr_q")
        code, out, err = self.run_agent(["tell", "t__reviewer", "--kind", "qa-passed", "--commit", self.sha,
                                         "--branch", "mg/t", "--base", self.base])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sent_text(), "t QA PASSED, commit %s on branch mg/t, base %s, "
                                           "builder &t__build (thr_b)" % (self.sha, self.base))
        self.assertEqual(self.rt.sent[0][0], "thr_r")
        row = self.log()[0]
        self.assertEqual((row["kind"], row["topic"], row["commit"], row["delivery"]),
                         ("qa-passed", "t", self.sha, "queued"))

    def test_qa_passed_on_the_working_tree(self):
        self.as_thread("thr_q")
        code, _, err = self.run_agent(["tell", "t__reviewer", "--kind", "qa-passed", "--commit",
                                       "working-tree", "--branch", "b", "--base", self.base])
        self.assertEqual(code, 0, err)
        self.assertIn("commit working tree on branch b", self.sent_text())

    def test_review_findings_carry_qas_fields_and_the_report_path(self):
        self.as_thread("thr_r")
        code, _, err = self.run_agent(["tell", "t__review-skeptic", "--kind", "review-findings", "--review", "01",
                                       "--commit", self.sha, "--branch", "b", "--base", self.base])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sent_text(), "t findings: S/reports/t__review-01.md, commit %s on branch b, "
                                           "base %s, builder &t__build (thr_b)" % (self.sha, self.base))

    def test_review_findings_need_the_report_to_exist(self):
        self.as_thread("thr_r")
        code, _, err = self.run_agent(["tell", "t__review-skeptic", "--kind", "review-findings", "--review", "02",
                                       "--commit", self.sha, "--branch", "b", "--base", self.base])
        self.assertEqual(code, 2)
        self.assertIn("t__review-02.md does not exist", err)
        self.assertEqual(self.rt.sent, [])

    def test_committed_and_review_passed_and_the_rest(self):
        self.run_agent(["tell", "t__review-skeptic", "--kind", "committed", "--commit", self.sha,
                        "--branch", "mg/t"])
        self.assertEqual(self.sent_text(0), "t committed tested tree as %s on branch mg/t" % self.sha)
        self.as_thread("thr_s")
        self.run_agent(["tell", "lead", "--kind", "review-passed", "--commit", self.sha, "--branch", "mg/t",
                        "--base", self.base])
        self.assertEqual(self.rt.sent[0][0], "thr_lead")
        self.rt.sent.clear()
        self.run_agent(["tell", "butler", "--kind", "review-passed", "--commit", self.sha, "--branch", "mg/t",
                        "--base", self.base])
        self.assertEqual(self.sent_text(0), "t review PASSED, commit %s on branch mg/t, base %s, "
                                            "builder &t__build (thr_b)" % (self.sha, self.base))
        self.as_thread("thr_butler")
        for name, kind, expected in (("main__qa", "merged", "merged "), ("t__build", "pushed", "pushed ")):
            self.rt.sent.clear()
            self.run_agent(["tell", name, "--kind", kind, "--commit", self.sha])
            self.assertEqual(self.sent_text(0), expected + self.sha)
        self.as_thread("thr_mqa")
        self.run_agent(["tell", "butler", "--kind", "main-qa-passed", "--commit", self.sha])
        self.assertEqual(self.sent_text(0), "main QA PASSED " + self.sha)

    def test_main_qa_failed_carries_the_defects_from_stdin(self):
        self.as_thread("thr_mqa")
        code, _, err = self.run_agent(["tell", "butler", "--kind", "main-qa-failed", "--commit", self.sha],
                                      "Round 1.\n\nD1. broken\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sent_text(), "main QA FAILED %s\n\nRound 1.\n\nD1. broken" % self.sha)

    def test_a_short_sha_is_sent_in_full(self):
        code, _, err = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s",
                                       "--commit", self.sha[:8]])
        self.assertEqual(code, 0, err)
        self.assertIn("commit " + self.sha, self.sent_text())

    # checks before sending
    def test_a_missing_commit_fails_before_sending(self):
        self.as_thread("thr_q")
        code, _, err = self.run_agent(["tell", "t__reviewer", "--kind", "qa-passed", "--branch", "b",
                                       "--base", self.base])
        self.assertEqual(code, 2)
        self.assertIn("kind qa-passed needs --commit", err)
        self.assertEqual((self.rt.sent, self.log()), ([], []))

    def test_every_missing_flag_is_listed_at_once(self):
        self.as_thread("thr_q")
        code, _, err = self.run_agent(["tell", "t__reviewer", "--kind", "qa-passed"])
        self.assertEqual(code, 2)
        for flag in ("--commit", "--branch", "--base"):
            self.assertIn("needs " + flag, err)

    def test_a_sha_git_does_not_know_fails(self):
        code, _, err = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s",
                                       "--commit", "deadbeef" * 5])
        self.assertEqual(code, 2)
        self.assertIn("--commit", err)
        self.assertIn("not a commit git knows", err)
        self.assertEqual(self.rt.sent, [])

    def test_working_tree_is_only_for_kinds_that_allow_it(self):
        code, _, err = self.run_agent(["tell", "butler", "--kind", "merged", "--commit", "working-tree"])
        self.assertEqual(code, 2)
        self.assertIn("not a commit git knows", err)

    def test_a_flag_the_kind_does_not_use_is_refused(self):
        code, _, err = self.run_agent(["tell", "butler", "--kind", "merged", "--commit", self.sha,
                                       "--branch", "b"])
        self.assertEqual(code, 2)
        self.assertIn("--branch is not used by kind merged", err)

    def test_a_field_flag_without_kind_is_refused(self):
        code, _, err = self.run_agent(["tell", "t__qa", "--commit", self.sha])
        self.assertEqual(code, 2)
        self.assertIn("goes with --kind", err)

    def test_a_kind_to_a_name_that_is_not_a_link_lists_the_registered_names(self):
        code, _, err = self.run_agent(["tell", "nobody", "--kind", "merged", "--commit", self.sha])
        self.assertEqual(code, 2)
        self.assertIn("&butler", err)
        self.assertEqual(self.rt.sent, [])

    def test_plain_tell_to_lead_still_points_to_tell_lead(self):
        code, _, err = self.run_agent(["tell", "lead"], "x\n")
        self.assertEqual(code, 2)
        self.assertIn("tell-lead", err)

    # the next link is not registered
    def test_a_hand_off_to_an_unregistered_link_reaches_the_lead_with_the_waiting_line(self):
        self.as_thread("thr_q")
        code, out, err = self.run_agent(["tell", "t2__reviewer", "--kind", "qa-passed", "--commit", self.sha,
                                         "--branch", "b", "--base", self.base, "--topic", "t",
                                         "--builder", "thr_b"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.sent[0][0], "thr_lead")
        text = self.sent_text()
        self.assertIn("Hand-off for `&t2__reviewer`, which is not spawned yet.", text)
        self.assertTrue(text.endswith("t QA PASSED, commit %s on branch b, base %s, builder &t__build "
                                      "(thr_b)" % (self.sha, self.base)))
        self.assertIn("waiting for Lead on &t2__reviewer", out)
        row = self.log()[0]
        self.assertEqual((row["to"], row["kind"], row["forKind"], row["next"]),
                         ("lead", "handoff-unspawned", "qa-passed", "t2__reviewer"))

    def test_a_hand_off_to_a_registered_link_goes_straight_to_it(self):
        code, out, _ = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s"])
        self.assertEqual(self.rt.sent[0][0], "thr_q")
        self.assertNotIn("waiting for Lead", out)

    # delivery of a chain message uses the same rules
    def test_a_chain_message_is_retried_once_then_not_delivered(self):
        self.rt.tell_script = [bb_failure("busy", "later"), bb_failure("busy", "later")]
        code, _, err = self.run_agent(["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s"])
        self.assertEqual(code, 1)
        self.assertIn("NOT delivered", err)
        self.assertEqual([r["kind"] for r in self.log()], ["ready-for-qa", "ready-for-qa"])

    # compact-lead
    def test_compact_lead_from_another_thread_refuses(self):
        code, _, err = self.run_agent(["compact-lead"])
        self.assertEqual(code, 2)
        self.assertIn("&butler only", err)
        self.assertEqual(self.rt.sent, [])
        self.assertNotIn("wait", [c[0] for c in self.rt.calls])

    def test_compact_lead_waits_then_compacts_and_tells_in_one_call(self):
        self.as_thread("thr_butler")
        code, out, err = self.run_agent(["compact-lead"])
        self.assertEqual(code, 0, err)
        self.assertEqual([c for c in self.rt.calls if c[0] in ("wait", "tell", "compact")],
                         [("wait", "thr_lead", "20m"), ("tell", "thr_lead", "queue")])
        self.assertEqual(self.rt.compact_first_flags, [True])
        self.assertEqual(self.sent_text(), "Lead compacted. Go on from your snapshot.")
        self.assertIn("Lead compacted", out)
        row = self.log()[0]
        self.assertEqual((row["from"], row["to"], row["kind"], row["delivery"]),
                         ("butler", "lead", "compacted", "queued"))

    def test_compact_lead_tries_three_times_then_tells_the_lead_it_is_not_compacted(self):
        self.as_thread("thr_butler")
        self.rt.wait_script = [{"matched": False, "exit": 2}] * 3
        code, _, err = self.run_agent(["compact-lead", "--timeout", "1m"])
        self.assertEqual(code, 1)
        self.assertEqual(len([c for c in self.rt.calls if c[0] == "wait"]), 3)
        self.assertEqual(len(self.rt.sent), 1)
        self.assertEqual(self.rt.compact_first_flags, [False])
        self.assertIn("Lead not compacted after 3 tries. Last problem: the Lead was still busy after 1m",
                      self.sent_text())
        self.assertEqual(self.log()[-1]["kind"], "not-compacted")

    def test_compact_lead_retries_a_refusal_and_then_succeeds(self):
        self.as_thread("thr_butler")
        self.rt.tell_script = [bb_failure("busy", "Lead is busy")]
        code, _, err = self.run_agent(["compact-lead"])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.rt.sent), 2)
        self.assertEqual(self.rt.compact_first_flags, [True, True])

    def test_compact_lead_unconfirmed_is_not_retried_and_does_not_claim_failure(self):
        self.as_thread("thr_butler")
        self.rt.tell_script = [{"delivery": "unknown", "id": None}]
        code, _, err = self.run_agent(["compact-lead"])
        self.assertEqual(code, 1)
        self.assertIn("UNCONFIRMED", err)
        self.assertEqual(len(self.rt.sent), 1)

    # templates
    def test_every_chain_and_lead_template_is_rendered_by_a_call_in_this_file(self):
        templates.RENDERED.clear()
        shas = ["--commit", self.sha]
        flow = [
            ("thr_b", ["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s"], ""),
            ("thr_b", ["tell", "t__qa", "--kind", "ready-for-qa", "--summary", "s"] + shas, ""),
            ("thr_q", ["tell", "t__reviewer", "--kind", "qa-passed", "--branch", "b", "--base", self.base]
             + shas, ""),
            ("thr_r", ["tell", "t__review-skeptic", "--kind", "review-findings", "--review", "01",
                       "--branch", "b", "--base", self.base] + shas, ""),
            ("thr_b", ["tell", "t__review-skeptic", "--kind", "committed", "--branch", "b"] + shas, ""),
            ("thr_s", ["tell", "butler", "--kind", "review-passed", "--branch", "b", "--base", self.base]
             + shas, ""),
            ("thr_butler", ["tell", "main__qa", "--kind", "merged"] + shas, ""),
            ("thr_butler", ["tell", "t__build", "--kind", "pushed"] + shas, ""),
            ("thr_mqa", ["tell", "butler", "--kind", "main-qa-passed"] + shas, ""),
            ("thr_mqa", ["tell", "butler", "--kind", "main-qa-failed"] + shas, "defects\n"),
            ("thr_q", ["tell", "t2__reviewer", "--kind", "qa-passed", "--branch", "b", "--base", self.base,
                       "--topic", "t", "--builder", "thr_b"] + shas, ""),
            ("thr_butler", ["compact-lead"], ""),
        ]
        for thread, argv, stdin in flow:
            self.as_thread(thread)
            code, _, err = self.run_agent(argv, stdin)
            self.assertEqual(code, 0, "%s: %s" % (argv, err))
        self.as_thread("thr_butler")
        self.rt.wait_script = [{"matched": False, "exit": 2}] * 3
        self.assertEqual(self.run_agent(["compact-lead"])[0], 1)
        in_groups = lambda refs: {r for r in refs if r.split("/")[0] in ("chain", "lead")}
        self.assertEqual(in_groups(templates.RENDERED), in_groups(templates.all_refs()))
        self.assertEqual(len(in_groups(templates.all_refs())), 13)


if __name__ == "__main__":
    unittest.main()
