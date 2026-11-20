import json
import os
import shutil
import tempfile
import unittest

from fake_runtime import (FakeRuntime, bb_failure, load_script, make_team, run_cli, thread_usage_answer,
                          tree_row)
from moelib import templates
from moelib import usage as usagelib
from moelib.runtime import (EVENT_TOKENS, EVENT_TURN_REQUESTED, EVENT_TURN_STARTED, KEY_TOKENS,
                            BbRuntime)

lead_cli = load_script("moe-lead.py")
SPLIT = "2026-11-16T15:54:00Z"
BEFORE, AFTER = "2026-11-16T10:00:00Z", "2026-11-17T10:00:00Z"


class StubRuntime(BbRuntime):
    """The real parsing code over canned bb answers: `answers` maps a command's words to its JSON."""

    def __init__(self, answers):
        super().__init__(cli="bb-not-run")
        self.answers = answers
        self.asked = []

    def _json(self, args, stdin=None):
        self.asked.append(list(args))
        key = " ".join(args)
        for prefix, answer in self.answers.items():
            if key.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError("unexpected bb call: %s" % key)


def request(trigger_data, at_ms=1000, target="new-turn", model="m1"):
    data = {"target": {"kind": target}, "execution": {"model": model}}
    data.update(trigger_data)
    return {"type": EVENT_TURN_REQUESTED, "createdAt": at_ms, "data": data}


class RuntimeParsingTest(unittest.TestCase):
    def test_tree_walks_every_depth_and_includes_archived(self):
        def thread(i, parent, archived=None):
            return {"id": i, "parentThreadId": parent, "title": "t" + i, "status": "idle",
                    "providerId": "p", "parentNotifications": "stuck", "createdAt": 0, "archivedAt": archived}
        answers = {
            "thread show r": {"thread": {"id": "r", "title": "root", "status": "idle"}},
            "thread list --parent-thread r ": [thread("a", "r"), thread("b", "r", archived=5)],
            "thread list --parent-thread a ": [thread("c", "a", archived=5)],
            "thread list --parent-thread b ": [],
            "thread list --parent-thread c ": [thread("d", "c")],
            "thread list --parent-thread d ": [thread("a", "d")],  # a loop must not repeat a row
        }
        rt = StubRuntime(answers)
        rows = rt.thread_tree("r")
        self.assertEqual([(r["id"], r["depth"], r["archived"]) for r in rows],
                         [("r", 0, False), ("a", 1, False), ("b", 1, True), ("c", 2, True), ("d", 3, False)])
        self.assertIsNone(rows[0]["parent"])
        listing = [a for a in rt.asked if a[:2] == ["thread", "list"]]
        self.assertTrue(listing and all("--include-archived" in a for a in listing))

    def test_usage_counts_each_trigger_and_keeps_a_steer_out_of_the_turns(self):
        ms = 1_700_000_000_000
        events = [
            request({"source": "spawn", "initiator": "user"}, ms, "thread-start"),
            request({"source": "tell", "initiator": "user"}, ms),
            request({"source": "tell", "initiator": "user"}, ms, "steer"),
            request({"source": "tell", "initiator": "agent", "senderThreadId": "thr_x"}, ms),
            request({"source": "tell", "initiator": "system", "systemMessageKind": "child-completed",
                     "systemMessageSubject": {"threadId": "thr_kid"}}, ms),
            request({"source": "tell", "initiator": "system", "systemMessageKind": "child-failed"}, ms),
            request({"source": "tell", "initiator": "system", "systemMessageKind": "child-needs-attention"}, ms),
            request({"source": "tell", "initiator": "system", "systemMessageKind": "something-new"}, ms),
            {"type": EVENT_TURN_STARTED, "createdAt": ms},
            {"type": EVENT_TURN_STARTED, "createdAt": ms + 1000},
            {"type": EVENT_TOKENS, "seq": 5, "scope": {"turnId": "sess9-t3"}, "data": {KEY_TOKENS: {
                "total": {"totalTokens": 100, "outputTokens": 7}}}},
            {"type": EVENT_TOKENS, "seq": 9, "scope": {"turnId": "sess10-t4"}, "data": {KEY_TOKENS: {
                "total": {"totalTokens": 250, "outputTokens": 9}}}},
        ]
        context = {"usage": {"snapshot": {"model": "m-now", "usedTokens": 40, "contextWindowTokens": 1000},
                             "cost": {"amount": 1.5, "currency": "USD"}}}
        rt = StubRuntime({"thread log t": events, "thread context t": context})
        got = rt.thread_usage("t")
        self.assertEqual([r["trigger"] for r in got["requests"]],
                         ["spawn", "user", "user", "agent", "child-done", "child-failed-or-blocked",
                          "child-failed-or-blocked", "other"])
        self.assertEqual([r["steer"] for r in got["requests"]],
                         [False, False, True, False, False, False, False, False])
        self.assertEqual(got["requests"][3]["sender"], "thr_x")
        self.assertEqual(got["requests"][4]["about"], "thr_kid")
        self.assertEqual(len(got["turns"]), 2)  # 8 requests, 2 turns
        self.assertEqual(got["turns"][0], "2023-11-14T22:13:20Z")
        self.assertEqual(got["tokens"], {"total": 250, "output": 9, "session": "sess10", "partial": True})
        self.assertEqual(got["context"], {"used": 40, "window": 1000, "cost": {"amount": 1.5, "currency": "USD"}})
        self.assertEqual(got["model"], "m-now")

    def test_usage_without_tokens_or_context(self):
        rt = StubRuntime({"thread log t": [], "thread context t": bb_failure()})
        got = rt.thread_usage("t")
        self.assertEqual((got["turns"], got["requests"], got["tokens"], got["context"], got["model"]),
                         ([], [], None, None, None))


def team_with(root, agents):
    return make_team(root, agents={n: {"thread": t, "role": "x"} for n, t in agents.items()})


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.base, ignore_errors=True))
        self.root = os.path.join(self.base, "thread-storage", "thr_lead")
        self.rt = FakeRuntime(thread="thr_lead", data_dir=self.base, storage=self.root)
        team_with(self.root, {})

    def usage(self, *flags, rt=None):
        return run_cli(lead_cli, ["usage"] + list(flags), rt or self.rt)

    def report(self, *flags):
        code, out, err = self.usage("--json", *flags)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def snapshot_file(self):
        return usagelib.snapshot_path(self.root)

    def snapshot_text(self):
        with open(self.snapshot_file()) as f:
            return f.read()

    def drop_team(self):
        os.remove(os.path.join(self.root, "logs", "team.json"))

    def deep_tree(self):
        """Depth 3, an archived thread, a registered agent, a `&name` title, an untitled thread."""
        self.rt.tree = [
            tree_row("thr_lead", None, "the lead", 0),
            tree_row("thr_b", "thr_lead", "&auth__build", 1),
            tree_row("thr_q", "thr_lead", "&auth__qa", 1, archived=True),
            tree_row("thr_s", "thr_b", "throwaway: spawn check", 2, archived=True),
            tree_row("thr_ss", "thr_s", None, 3, notifications="auto"),
            tree_row("thr_t", "thr_lead", "&butler", 1, notifications="auto"),
            tree_row("thr_x", "thr_lead", "something else", 1),
        ]
        team_with(self.root, {"auth__build": "thr_b", "butler": "thr_t"})


class WalkTest(UsageTest):
    def test_a_tree_of_depth_3_with_archived_and_unregistered_threads_is_walked_whole(self):
        self.deep_tree()
        report = self.report()
        self.assertEqual([t["id"] for t in report["threads"]],
                         ["thr_lead", "thr_b", "thr_q", "thr_s", "thr_ss", "thr_t", "thr_x"])
        self.assertEqual(report["depth"], 3)
        self.assertEqual(report["archived"], 2)
        read = [c[1] for c in self.rt.calls if c[0] == "thread_usage"]
        self.assertEqual(sorted(read), sorted(t["id"] for t in report["threads"]))

    def test_names_come_from_the_team_then_the_title_then_the_id_and_all_count(self):
        self.deep_tree()
        for thread, usage in (("thr_b", thread_usage_answer(turns=[AFTER] * 2, total=10)),
                              ("thr_q", thread_usage_answer(turns=[AFTER] * 3, total=20)),
                              ("thr_x", thread_usage_answer(turns=[AFTER] * 4, total=30)),
                              ("thr_ss", thread_usage_answer(turns=[AFTER] * 5, total=40))):
            self.rt.usage[thread] = usage
        report = self.report()
        by_id = {t["id"]: t for t in report["threads"]}
        self.assertEqual((by_id["thr_lead"]["name"], by_id["thr_b"]["name"], by_id["thr_t"]["name"]),
                         ("lead", "auth__build", "butler"))  # from the team
        self.assertEqual((by_id["thr_q"]["name"], by_id["thr_q"]["named_by"]), ("auth__qa", "title"))
        self.assertEqual((by_id["thr_x"]["name"], by_id["thr_x"]["named_by"]), ("thr_x", "id"))
        self.assertEqual((by_id["thr_ss"]["name"], by_id["thr_ss"]["named_by"]), ("thr_ss", "id"))
        self.assertTrue(by_id["thr_q"]["unregistered"] and by_id["thr_x"]["unregistered"])
        self.assertFalse(by_id["thr_b"]["unregistered"])
        self.assertEqual(report["total"]["turns"], 14)  # unregistered threads are in the totals
        self.assertEqual(report["total"]["tokens"], 100)

    def test_a_marker_in_front_of_a_title_does_not_change_the_name(self):
        self.rt.tree = [tree_row("thr_lead", None, "the lead", 0),
                        tree_row("thr_q", "thr_lead", "❓ &auth__qa", 1),
                        tree_row("thr_r", "thr_lead", "❗️ &auth__reviewer", 1)]
        by_id = {t["id"]: t for t in self.report()["threads"]}
        self.assertEqual((by_id["thr_q"]["name"], by_id["thr_q"]["named_by"], by_id["thr_q"]["topic"]),
                         ("auth__qa", "title", "auth"))
        self.assertEqual((by_id["thr_r"]["name"], by_id["thr_r"]["named_by"]), ("auth__reviewer", "title"))

    def test_topics_follow_the_name_and_children_join_their_parents(self):
        self.deep_tree()
        topics = {t["id"]: t["topic"] for t in self.report()["threads"]}
        self.assertEqual(topics, {"thr_lead": "-", "thr_b": "auth", "thr_q": "auth", "thr_s": "auth",
                                  "thr_ss": "auth", "thr_t": "-", "thr_x": "-"})

    def test_without_a_team_names_come_from_titles_and_nothing_is_flagged(self):
        self.drop_team()
        self.rt.tree = [tree_row("thr_lead", None, "the lead", 0), tree_row("thr_b", "thr_lead", "&auth__build", 1)]
        report = self.report("--thread", "thr_lead")
        self.assertEqual([t["name"] for t in report["threads"]], ["root", "auth__build"])
        self.assertFalse(any(t["unregistered"] for t in report["threads"]))

    def test_a_thread_that_cannot_be_read_counts_as_zero_and_is_listed(self):
        self.deep_tree()
        self.rt.usage_errors["thr_b"] = bb_failure()
        self.rt.usage["thr_t"] = thread_usage_answer(turns=[AFTER], total=5)
        code, out, _ = self.usage()
        self.assertEqual(code, 0)
        self.assertIn("could not be read", out)
        self.assertIn("thr_b", out)
        report = self.report("--peek")
        self.assertEqual(report["unread"], ["thr_b"])
        self.assertEqual(report["total"]["turns"], 1)


class CountTest(UsageTest):
    def test_each_trigger_is_counted_for_the_lead_and_a_steer_is_not_a_turn(self):
        self.rt.usage["thr_lead"] = thread_usage_answer(
            turns=[BEFORE, AFTER],
            requests=[(BEFORE, "spawn"), (BEFORE, "user"), (AFTER, "user", "steer"), (AFTER, "agent"),
                      (BEFORE, "child-done"), (AFTER, "child-done"), (AFTER, "child-failed-or-blocked"),
                      (AFTER, "other")])
        lead = self.report("--split-at", SPLIT)["lead"]
        self.assertEqual(lead["triggers"], {"user": 2, "agent": 1, "child-done": 2,
                                            "child-failed-or-blocked": 1, "spawn": 1, "other": 1})
        self.assertEqual(lead["triggers_before"]["child-done"], 1)
        self.assertEqual(lead["triggers_after"]["child-done"], 1)
        self.assertEqual((lead["requests"], lead["steered"], lead["turns"]), (8, 1, 2))
        self.assertEqual((lead["turns_before"], lead["turns_after"]), (1, 1))

    def test_the_text_shows_the_split_and_who_woke_the_lead_after_it(self):
        self.deep_tree()
        self.rt.usage["thr_lead"] = thread_usage_answer(
            turns=[BEFORE], requests=[(BEFORE, "child-done"), (AFTER, "child-done")], used=500)
        self.rt.usage["thr_lead"]["requests"][1]["about"] = "thr_t"
        code, out, err = self.usage("--split-at", SPLIT, "--peek")
        self.assertEqual(code, 0, err)
        self.assertIn("child-done 1/1", out)
        self.assertIn("came from: butler 1", out)

    def test_by_notifications_and_by_model_group_the_threads_under_the_lead(self):
        self.deep_tree()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER], model="big")
        report_text = self.usage("--by", "notifications")[1]
        rows = {line.split()[0]: line.split() for line in report_text.splitlines()}
        self.assertEqual(rows["auto"][1], "2")   # butler and the deepest throwaway
        self.assertEqual(rows["stuck"][1], "4")
        text = self.usage("--by", "model", "--peek")[1]
        self.assertIn("big", text)


class NoEstimateTest(UsageTest):
    def test_there_is_no_input_estimate_in_the_text_or_the_json(self):
        self.deep_tree()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER] * 4, total=100, used=5000)
        self.assertNotIn("estimat", self.usage("--threads", "--peek")[1].lower())
        self.assertNotIn("~", self.usage("--peek")[1])
        self.assertNotIn("estimated_input", self.usage("--json", "--peek")[1])


class SnapshotTest(UsageTest):
    def ask(self, *flags):
        return self.report(*flags)

    def test_the_first_ask_saves_a_snapshot_and_has_no_deltas(self):
        self.rt.usage["thr_lead"] = thread_usage_answer(turns=[AFTER] * 3, total=100)
        report = self.ask()
        self.assertIsNone(report["deltas"])
        with open(self.snapshot_file()) as f:
            saved = json.load(f)
        self.assertEqual(saved["threads"]["thr_lead"], {"turns": 3, "requests": 0, "tokens_total": 100,
                                                        "session": "s1", "accumulated": 100})

    def test_turn_and_request_deltas_are_exact_and_a_same_session_token_delta_is_the_difference(self):
        self.deep_tree()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER] * 2, requests=[(AFTER, "user")], total=1000)
        self.ask()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER] * 5, requests=[(AFTER, "user")] * 4,
                                                     total=1800)
        report = self.ask()
        by_id = {t["id"]: t for t in report["threads"]}
        delta = by_id["thr_b"]["delta"]
        self.assertEqual((delta["turns"], delta["requests"], delta["tokens"], delta["lower_bound"]),
                         (3, 3, 800, False))
        self.assertEqual(by_id["thr_b"]["accumulated"], 1800)
        self.assertEqual(report["deltas"]["turns"], 3)

    def test_a_new_session_gives_the_total_marked_as_a_lower_bound_and_accumulates(self):
        self.rt.usage["thr_lead"] = thread_usage_answer(turns=[AFTER], total=1000, session="old")
        self.ask()
        self.rt.usage["thr_lead"] = thread_usage_answer(turns=[AFTER] * 2, total=300, session="new")
        code, out, _ = self.usage("--peek")
        self.assertEqual(code, 0)
        self.assertIn("≥ +300", out.splitlines()[-2])  # the since-last line
        report = self.ask()
        lead = report["threads"][0]
        self.assertEqual((lead["delta"]["tokens"], lead["delta"]["lower_bound"]), (300, True))
        self.assertEqual(lead["accumulated"], 1300)  # tokens become a lower bound across asks
        self.assertTrue(report["deltas"]["lower_bound"])

    def test_a_thread_new_since_the_last_ask_counts_all_it_has(self):
        self.deep_tree()
        self.ask()
        self.rt.tree.append(tree_row("thr_n", "thr_lead", "&late__build", 1))
        self.rt.usage["thr_n"] = thread_usage_answer(turns=[AFTER] * 2, total=50)
        report = self.ask("--peek")
        new = report["threads"][-1]
        self.assertEqual((new["delta"]["turns"], new["delta"]["tokens"], new["delta"]["new"]), (2, 50, True))
        self.assertEqual(report["deltas"]["new_threads"], 1)

    def test_a_thread_unreadable_now_keeps_what_the_last_ask_saw(self):
        self.deep_tree()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER] * 4, total=100)
        self.ask()
        self.rt.usage_errors["thr_b"] = bb_failure()
        report = self.ask("--peek")
        b = [t for t in report["threads"] if t["id"] == "thr_b"][0]
        self.assertEqual((b["turns"], b["tokens_total"], b["delta"]["turns"]), (4, 100, 0))

    def test_peek_writes_no_file_and_still_compares(self):
        self.rt.usage["thr_lead"] = thread_usage_answer(turns=[AFTER], total=10)
        self.ask("--peek")
        self.assertFalse(os.path.exists(self.snapshot_file()))
        self.ask()
        self.assertTrue(os.path.exists(self.snapshot_file()))
        before = self.snapshot_text()
        self.rt.usage["thr_lead"] = thread_usage_answer(turns=[AFTER] * 2, total=20)
        report = self.ask("--peek")
        self.assertEqual(report["deltas"]["turns"], 1)
        self.assertEqual(self.snapshot_text(), before)

    def test_thread_works_from_any_thread_without_team_json_and_writes_nothing(self):
        self.drop_team()
        other = FakeRuntime(thread="thr_builder", data_dir=self.base,
                            storage=os.path.join(self.base, "thread-storage", "thr_builder"))
        other.tree = [tree_row("thr_lead", None, "the lead", 0), tree_row("thr_b", "thr_lead", "&a__b", 1)]
        other.usage["thr_b"] = thread_usage_answer(turns=[AFTER], total=10)
        code, out, err = run_cli(lead_cli, ["usage", "--thread", "thr_lead"], other)
        self.assertEqual(code, 0, err)
        self.assertIn("Read-only (--thread)", out)
        self.assertEqual(self.written_files(), [])

    def test_thread_names_from_the_roots_registry_and_reads_its_snapshot_without_changing_it(self):
        self.deep_tree()
        self.rt.usage["thr_b"] = thread_usage_answer(turns=[AFTER], total=10)
        self.ask()
        before = self.snapshot_text()
        other = FakeRuntime(thread="thr_builder", data_dir=self.base)
        other.tree = self.rt.tree
        other.usage["thr_b"] = thread_usage_answer(turns=[AFTER] * 3, total=40)
        report = json.loads(run_cli(lead_cli, ["usage", "--thread", "thr_lead", "--json"], other)[1])
        self.assertEqual(report["threads"][0]["name"], "lead")
        self.assertEqual(report["deltas"]["turns"], 2)
        self.assertEqual(self.snapshot_text(), before)

    def test_another_threads_registry_is_not_used_for_a_thread_that_is_not_its_lead(self):
        self.deep_tree()
        other = FakeRuntime(thread="thr_builder", data_dir=self.base)
        other.tree = [tree_row("thr_b", None, "&auth__build", 0)]
        report = json.loads(run_cli(lead_cli, ["usage", "--thread", "thr_b", "--json"], other)[1])
        self.assertEqual(report["threads"][0]["name"], "root")

    def written_files(self):
        found = []
        for folder, _, files in os.walk(self.base):
            found += [os.path.join(folder, f) for f in files]
        return found

    def test_without_thread_a_thread_that_is_not_the_lead_is_refused(self):
        self.deep_tree()
        stranger = FakeRuntime(thread="thr_other", storage=self.root)
        code, _, err = run_cli(lead_cli, ["usage"], stranger)
        self.assertEqual(code, 2)
        self.assertIn("not the Lead", err)

    def test_without_a_team_file_usage_asks_for_setup(self):
        self.drop_team()
        code, _, err = self.usage()
        self.assertEqual(code, 2)
        self.assertIn("setup", err)

    def test_a_bad_split_time_is_refused(self):
        self.deep_tree()
        code, _, err = self.usage("--split-at", "yesterday")
        self.assertEqual(code, 2)
        self.assertIn("--split-at", err)


class OutputTest(UsageTest):
    def many(self, count):
        self.rt.tree = [tree_row("thr_lead", None, "the lead", 0)]
        agents = {}
        for i in range(count):
            tid = "thr_%02d" % i
            self.rt.tree.append(tree_row(tid, "thr_lead", "&topic%02d__build" % i, 1,
                                         notifications="auto" if i % 2 else "stuck"))
            agents["topic%02d__build" % i] = tid
            self.rt.usage[tid] = thread_usage_answer(turns=[BEFORE, AFTER], requests=[(AFTER, "user")],
                                                     total=1000 * (i + 1), used=5000)
        team_with(self.root, agents)
        self.rt.usage["thr_lead"] = thread_usage_answer(
            turns=[BEFORE, AFTER], requests=[(BEFORE, "user"), (AFTER, "child-done"), (BEFORE, "spawn")], used=9000)
        self.rt.usage["thr_lead"]["requests"][1]["about"] = "thr_01"

    def test_the_default_output_stays_within_20_lines_with_40_threads(self):
        self.many(40)
        for flags in ((), ("--split-at", SPLIT), ("--by", "notifications"), ("--by", "model")):
            lines = self.usage(*flags)[1].splitlines()
            self.assertLessEqual(len(lines), 20, "\n".join(lines))
        self.rt.usage_errors["thr_03"] = bb_failure()
        lines = self.usage("--split-at", SPLIT)[1].splitlines()  # second ask: with deltas, and an unreadable thread
        self.assertLessEqual(len(lines), 20, "\n".join(lines))
        self.assertIn("(30 more)", "\n".join(lines))  # 40 topics: 10 shown, the rest summed

    def test_threads_adds_one_row_per_thread(self):
        self.many(5)
        out = self.usage("--threads", "--peek")[1].splitlines()
        threads = out[out.index("") + 1:]  # the per-thread table follows the blank line
        self.assertEqual(len([l for l in threads if l.startswith("topic0")]), 5)
        self.assertIn("lead", [l.split()[0] for l in out if l])

    def test_json_holds_every_thread_and_parses(self):
        self.many(12)
        report = self.report("--peek")
        self.assertEqual(len(report["threads"]), 13)
        self.assertEqual(report["total"]["threads"], 13)

    def test_every_usage_template_is_rendered_by_the_verb(self):
        self.deep_tree()
        self.rt.usage["thr_lead"] = thread_usage_answer(
            turns=[AFTER], requests=[(AFTER, "child-done")], used=100)
        self.rt.usage["thr_lead"]["requests"][0]["about"] = "thr_t"
        templates.RENDERED.clear()
        self.usage("--split-at", SPLIT, "--peek")           # read-only, no snapshot yet
        self.usage()                                        # first ask
        self.rt.usage_errors["thr_b"] = bb_failure()
        self.usage("--split-at", SPLIT)                     # since last ask, an unreadable thread
        group = {r for r in templates.all_refs() if r.startswith("usage/")}
        self.assertTrue(group)
        self.assertEqual({r for r in templates.RENDERED if r.startswith("usage/")}, group)


if __name__ == "__main__":
    unittest.main()
