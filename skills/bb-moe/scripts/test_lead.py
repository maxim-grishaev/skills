import os
import shutil
import tempfile
import unittest

from fake_runtime import FakeRuntime, bb_failure, load_script, make_git_repo, make_team, run_cli
from moelib import brief as brieflib
from moelib import team as teamlib
from moelib import templates

lead_cli = load_script("moe-lead.py")
SETUP = ["setup", "--provider", "claude-code", "--stronger", "model-strong", "--mid", "model-mid"]


class LeadTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.base, ignore_errors=True))
        self.root = os.path.join(self.base, "S")
        self.worktree = os.path.join(self.base, "lead")
        self.sha = make_git_repo(self.worktree)
        self.rt = FakeRuntime(thread="thr_lead", storage=self.root)
        self.rt.shown["environment"]["path"] = self.worktree

    def run_lead(self, argv, stdin="the body\n", rt=None):
        return run_cli(lead_cli, argv, rt or self.rt, stdin)

    def setup_team(self):
        code, _, err = self.run_lead(SETUP)
        self.assertEqual(code, 0, err)

    def brief(self, *flags, stdin="the body\n"):
        return self.run_lead(["brief"] + list(flags), stdin)

    def team(self):
        return teamlib.load_team(self.root)

    def section(self, name, heading):
        """The text of a '## <heading>' section of a saved brief, up to the next '## '."""
        text = self.brief_text(name)
        start = text.index("## " + heading)
        end = text.find("\n## ", start + 1)
        return text[start:end if end != -1 else len(text)]

    def brief_text(self, name, nn=1):
        for f in os.listdir(os.path.join(self.root, "briefs")):
            if f.startswith("%s-%02d-" % (name, nn)):
                with open(os.path.join(self.root, "briefs", f)) as fh:
                    return fh.read()


class SetupTest(LeadTest):
    def test_first_setup_records_the_lead_tiers_and_an_empty_registry(self):
        self.setup_team()
        team = self.team()
        self.assertEqual(team["lead"], {"thread": "thr_lead", "project": "proj_1", "environment": "env_lead",
                                        "worktree": self.worktree, "branch": "work", "isGitRepo": True})
        self.assertEqual(team["tiers"], {"provider": "claude-code", "stronger": "model-strong", "mid": "model-mid"})
        self.assertEqual(team["agents"], {})

    def test_first_setup_without_tiers_lists_what_is_missing_and_writes_nothing(self):
        code, _, err = self.run_lead(["setup", "--provider", "p"])
        self.assertEqual(code, 2)
        self.assertIn("--stronger, --mid", err)
        self.assertIsNone(self.team())

    def test_later_setup_changes_only_the_given_fields(self):
        self.setup_team()
        self.assertEqual(self.run_lead(["setup", "--weight", "light"])[0], 0)
        team = self.team()
        self.assertEqual((team["weight"], team["tiers"]["mid"]), ("light", "model-mid"))

    def test_later_setup_from_another_thread_refuses(self):
        self.setup_team()
        other = FakeRuntime(thread="thr_other", storage=self.root)
        code, _, err = self.run_lead(["setup", "--weight", "light"], rt=other)
        self.assertEqual(code, 2)
        self.assertIn("not the Lead", err)
        self.assertNotIn("weight", self.team())


class RefusalTest(LeadTest):
    def test_brief_from_a_thread_that_is_not_the_lead_refuses_and_writes_nothing(self):
        self.setup_team()
        other = FakeRuntime(thread="thr_other", storage=self.root)
        code, _, err = self.run_lead(["brief", "--name", "scout", "--role", "scout", "--task", "t",
                                      "--works-for", "architect"], rt=other)
        self.assertEqual(code, 2)
        self.assertIn("not the Lead", err)
        self.assertIn("thr_lead", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "briefs")))
        self.assertEqual(other.spawned, [])

    def test_brief_before_setup_says_to_run_setup(self):
        code, _, err = self.brief("--name", "scout", "--role", "scout", "--task", "t", "--works-for", "a")
        self.assertEqual(code, 2)
        self.assertIn("moe-lead.py setup", err)


class BriefTest(LeadTest):
    def setUp(self):
        super().setUp()
        self.setup_team()

    def test_bad_flags_are_all_reported_and_nothing_is_written_or_spawned(self):
        code, _, err = self.brief("--name", "&Bad Name", "--role", "nonsense", "--commit", "maybe",
                                  "--push", "yes", stdin="")
        self.assertEqual(code, 2)
        for fragment in ("--task is required", "--role nonsense", "--commit maybe", "give the name without '&'",
                         "empty body on stdin"):
            self.assertIn(fragment, err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "briefs")))
        self.assertEqual(self.rt.spawned, [])

    def test_dry_run_for_each_of_the_12_roles_renders_and_spawns_nothing(self):
        self.assertEqual(len(brieflib.ROLES), 12)
        for role in brieflib.ROLES:
            flags = ["--name", "t__" + role, "--role", role, "--task", "do " + role]
            if role == "scout":
                flags += ["--works-for", "architect"]
            if role == "custom":
                flags += ["--what", "a custom thing", "--tier", "mid", "--env", "lead"]
            if role in ("qa", "reviewer", "review-skeptic"):
                flags += ["--env", "lead"]  # the builder is not registered in a dry run
            code, out, err = self.brief(*flags)
            self.assertEqual(code, 0, "%s: %s" % (role, err))
            text = self.brief_text("t__" + role)
            self.assertIn("You are `&t__%s`" % role, text)
            self.assertIn("the body", text)
            self.assertNotIn("${", text)
            self.assertIn("dry run, nothing spawned", out)
        self.assertEqual(self.rt.spawned, [])

    def test_opening_matches_the_template_and_names_the_agent_script(self):
        self.brief("--name", "x__build", "--role", "build", "--task", "OAuth sign-in")
        text = self.brief_text("x__build")
        files = templates.render("brief/files-with-role",
                                 common_file=os.path.join(brieflib.REFERENCES, "roles", "common.md"),
                                 role_file=os.path.join(brieflib.REFERENCES, "roles", "build.md"))
        expected = templates.render("brief/opening", agent_name="x__build", what="the builder",
                                    task="OAuth sign-in", lead_id="thr_lead", agent_cli=lead_cli.AGENT_CLI,
                                    files=files, root_path=self.root,
                                    weight=brieflib.NO_WEIGHT)
        self.assertTrue(text.startswith(expected + "\n\n"))
        self.assertIn("moe-agent.py tell-lead`", expected)
        self.assertNotIn("bb thread tell", text)

    def test_builder_gets_a_new_worktree_from_the_leads_head(self):
        code, out, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--spawn")
        self.assertEqual(code, 0, err)
        spec = self.rt.spawned[0]
        self.assertEqual(spec["new_worktree_base"], self.sha)
        self.assertEqual((spec["provider"], spec["model"], spec["project"]), ("claude-code", "model-mid", "proj_1"))
        where = self.section("x__build", "Where you work")
        self.assertIn(self.sha, where)
        self.assertIn("the Lead's HEAD", where)

    def test_a_bad_base_commit_is_an_error(self):
        code, _, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--base", "nope")
        self.assertEqual(code, 2)
        self.assertIn("--base nope: not a commit", err)

    def test_spawn_registers_the_agent(self):
        code, out, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "legwork",
                                    "--works-for", "architect", "--spawn")
        self.assertEqual(code, 0, err)
        entry = self.team()["agents"]["x__scout"]
        self.assertEqual((entry["thread"], entry["role"], entry["model"], entry["worksFor"]),
                         ("thr_new1", "scout", "model-mid", "architect"))
        self.assertNotIn("permissionMode", entry)
        self.assertIn("spawned &x__scout: thread thr_new1", out)
        self.assertEqual(self.rt.spawned[0]["environment"], "env_lead")
        self.assertNotIn("permission_mode", self.rt.spawned[0])  # the default: inherit the Lead's mode

    def test_permission_mode_is_passed_to_spawn_and_to_the_dry_run_command(self):
        code, out, _ = self.brief("--name", "x__scout", "--role", "scout", "--task", "t", "--works-for", "a",
                                  "--permission-mode", "accept-edits")
        self.assertEqual(code, 0)
        self.assertIn("--permission-mode accept-edits", out)
        code, _, err = self.brief("--name", "y__scout", "--role", "scout", "--task", "t", "--works-for", "a",
                                  "--permission-mode", "accept-edits", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.spawned[0]["permission_mode"], "accept-edits")
        self.assertEqual(self.team()["agents"]["y__scout"]["permissionMode"], "accept-edits")

    def test_an_unknown_permission_mode_is_refused_by_the_parser(self):
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "t", "--works-for", "a",
                                  "--permission-mode", "yolo")
        self.assertEqual(code, 2)
        self.assertIn("yolo", err)

    def test_qa_joins_the_builders_environment_and_brief_says_whose(self):
        self.brief("--name", "x__build", "--role", "build", "--task", "t", "--spawn")
        self.rt.env_paths["env_new1"] = "/builder/worktree"
        code, _, err = self.brief("--name", "x__qa", "--role", "qa", "--task", "t", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.spawned[1]["environment"], "env_new1")
        where = self.section("x__qa", "Where you work")
        for value in ("&x__build", "/builder/worktree", "env_new1"):
            self.assertIn(value, where)

    def test_read_only_roles_say_so(self):
        self.brief("--name", "x__reviewer", "--role", "reviewer", "--task", "t", "--env", "lead")
        self.assertIn(templates.render("brief/read-only"), self.section("x__reviewer", "Where you work"))
        self.brief("--name", "x__qa", "--role", "qa", "--task", "t", "--env", "lead")
        self.assertNotIn(templates.render("brief/read-only"), self.section("x__qa", "Where you work"))

    def test_limits_and_team_sections(self):
        creds = os.path.join(self.base, "login.env")
        open(creds, "w").close()
        self.brief("--name", "x__build", "--role", "build", "--task", "t", "--commit", "yes",
                   "--start", "dev server on port 3000", "--creds", creds, "--peers", "x__qa,x__unspawned",
                   "--env", "lead")
        text = self.brief_text("x__build")
        self.assertIn("- May start: dev server on port 3000.", text)
        self.assertIn("- Commit: yes, on your branch. Push: no.", text)
        self.assertIn("- Credentials: `%s`." % creds, text)
        self.assertIn("- `&x__qa`: not spawned yet.", text)
        self.assertIn("- Every thread ID: `%s`." % teamlib.team_path(self.root), text)

    def test_only_the_butler_may_push(self):
        code, _, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--push", "yes")
        self.assertEqual(code, 2)
        self.assertIn("only &butler pushes", err)

    def test_a_registered_name_needs_replace_and_the_new_brief_is_numbered_on(self):
        self.brief("--name", "x__scout", "--role", "scout", "--task", "legwork", "--works-for", "a", "--spawn")
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "legwork", "--works-for", "a")
        self.assertEqual(code, 2)
        self.assertIn("already registered", err)
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "legwork", "--works-for", "a",
                                  "--replace", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.team()["agents"]["x__scout"]["replaces"], "thr_new1")
        self.assertIn("x__scout-02-legwork.md", self.team()["agents"]["x__scout"]["brief"])

    def test_a_missing_environment_id_in_the_spawn_answer_is_read_from_the_thread(self):
        self.rt.spawn_without_environment = True
        code, out, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.team()["agents"]["x__build"]["environment"], "env_new1")
        self.assertIn("environment env_new1", out)
        self.assertIn(("show", "thr_new1"), self.rt.calls)
        # and QA can now join the builder's worktree
        self.rt.env_paths["env_new1"] = "/builder/worktree"
        code, _, err = self.brief("--name", "x__qa", "--role", "qa", "--task", "t", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.spawned[1]["environment"], "env_new1")

    def test_the_agent_is_registered_before_the_environment_lookup(self):
        self.rt.spawn_without_environment = True
        seen = []
        real_show = self.rt.show

        def show(thread_id):
            seen.append(dict(self.team()["agents"]))  # what the registry holds at lookup time
            return real_show(thread_id)

        self.rt.show = show
        code, _, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--spawn")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen[0]["x__build"]["thread"], "thr_new1")
        self.assertIsNone(seen[0]["x__build"]["environment"])
        self.assertEqual(self.team()["agents"]["x__build"]["environment"], "env_new1")

    def test_team_section_lists_members_one_per_line_and_none_when_alone(self):
        self.brief("--name", "x__build", "--role", "build", "--task", "t", "--env", "lead",
                   "--peers", "x__qa,butler")
        team = self.section("x__build", "Team")
        self.assertIn("- `&x__qa`: not spawned yet.\n- `&butler`: not spawned yet.", team)
        self.assertIn("Every thread ID", team)
        self.brief("--name", "solo", "--role", "butler", "--task", "t")
        alone = self.section("solo", "Team")
        self.assertNotIn("&", alone.replace("Lead:", ""))
        self.assertIn("Every thread ID", alone)

    def test_an_environment_bb_never_shows_is_registered_null_with_a_warning(self):
        self.rt.spawn_without_environment = True
        self.rt.new_environment_visible = False
        saved = lead_cli.time.sleep
        lead_cli.time.sleep = lambda s: None
        self.addCleanup(lambda: setattr(lead_cli.time, "sleep", saved))
        code, _, err = self.brief("--name", "x__build", "--role", "build", "--task", "t", "--spawn")
        self.assertEqual(code, 0)
        self.assertIsNone(self.team()["agents"]["x__build"]["environment"])
        self.assertIn("no environment ID", err)

    def test_spawn_failure_keeps_the_brief_and_registers_nothing(self):
        self.rt.spawn_error = bb_failure("http_500", "server down")
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "t", "--works-for", "a", "--spawn")
        self.assertEqual(code, 1)
        self.assertIn("server down", err)
        self.assertIn("nothing registered", err)
        self.assertEqual(self.team()["agents"], {})
        self.assertIsNotNone(self.brief_text("x__scout"))

    def test_spawn_without_a_thread_id_says_it_may_exist_and_registers_nothing(self):
        self.rt.spawn_without_id = True
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "t", "--works-for", "a", "--spawn")
        self.assertEqual(code, 1)
        self.assertIn("before you spawn again", err)
        self.assertEqual(self.team()["agents"], {})

    def test_a_broken_template_sends_nothing_and_names_file_and_variable(self):
        saved = templates.TEMPLATE_DIR
        broken = os.path.join(self.base, "templates")
        shutil.copytree(saved, broken)
        with open(os.path.join(broken, "brief", "limits.md"), "a") as f:
            f.write("- Extra: ${surprise}\n")
        templates.TEMPLATE_DIR = broken
        self.addCleanup(lambda: setattr(templates, "TEMPLATE_DIR", saved))
        code, _, err = self.brief("--name", "x__scout", "--role", "scout", "--task", "t", "--works-for", "a", "--spawn")
        self.assertEqual(code, 2)
        self.assertIn(os.path.join("brief", "limits.md"), err)
        self.assertIn("missing variable surprise", err)
        self.assertEqual(self.rt.spawned, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "briefs")))


class VerbTest(LeadTest):
    """follow-up, tell, status, show, output, log, wait, retry, compact, stop."""

    def setUp(self):
        super().setUp()
        self.setup_team()
        for name in ("x__build", "x__qa"):
            role = name.split("__")[1]
            code, _, err = self.brief("--name", name, "--role", role, "--task", "t", "--env", "lead", "--spawn")
            self.assertEqual(code, 0, err)
        self.rt.sent.clear()
        self.build, self.qa = "thr_new1", "thr_new2"

    def messages(self):
        return teamlib.read_messages(self.root)

    # follow-up

    def test_follow_up_numbers_on_from_the_last_brief_and_sends_it_queued(self):
        self.assertTrue(os.path.exists(os.path.join(self.root, "briefs", "x__build-01-t.md")))
        open(os.path.join(self.root, "briefs", "x__build-02-fix.md"), "w").close()
        code, out, err = self.run_lead(["follow-up", "--name", "x__build", "--task", "fix round 1"],
                                       "User: \"go\".\nFix F1.\n")
        self.assertEqual(code, 0, err)
        path = os.path.join(self.root, "briefs", "x__build-03-fix-round-1.md")
        self.assertIn(path, out)
        thread, text, mode = self.rt.sent[0]
        self.assertEqual((thread, mode), (self.build, "queue"))
        with open(path) as f:
            self.assertEqual(f.read(), text + "\n")
        self.assertTrue(text.startswith(templates.render("brief/follow-up", body="").strip()))
        self.assertTrue(text.endswith("Fix F1."))
        logged = self.messages()[-1]
        self.assertEqual((logged["from"], logged["to"], logged["kind"], logged["delivery"]),
                         ("lead", "x__build", "follow-up", "queued"))

    def test_follow_up_with_now_steers(self):
        self.run_lead(["follow-up", "--name", "x__build", "--task", "stop", "--now"], "Stop.\n")
        self.assertEqual(self.rt.sent[0][2], "steer")

    def test_follow_up_to_an_unknown_agent_lists_the_registered_ones_and_sends_nothing(self):
        code, _, err = self.run_lead(["follow-up", "--name", "nobody", "--task", "t"], "x\n")
        self.assertEqual(code, 2)
        self.assertIn("&x__build", err)
        self.assertEqual(self.rt.sent, [])

    def test_follow_up_from_a_thread_that_is_not_the_lead_refuses(self):
        other = FakeRuntime(thread="thr_other", storage=self.root)
        code, _, err = self.run_lead(["follow-up", "--name", "x__build", "--task", "t"], "x\n", rt=other)
        self.assertEqual(code, 2)
        self.assertIn("not the Lead", err)
        self.assertEqual(other.sent, [])

    def test_a_bb_refusal_exits_1_with_not_delivered_and_keeps_the_brief(self):
        self.rt.tell_script = [bb_failure(), bb_failure()]
        saved = messaging_sleep()
        self.addCleanup(saved)
        code, _, err = self.run_lead(["follow-up", "--name", "x__build", "--task", "fix"], "x\n")
        self.assertEqual(code, 1)
        self.assertIn("NOT delivered", err)

    # tell

    def test_tell_sends_a_short_message_with_a_sender_line(self):
        code, _, err = self.run_lead(["tell", "x__qa"], "Run the suite again.\n")
        self.assertEqual(code, 0, err)
        thread, text, mode = self.rt.sent[0]
        self.assertEqual((thread, mode), (self.qa, "queue"))
        self.assertEqual(text, templates.render("from-lead/message", body="Run the suite again."))

    def test_tell_refuses_more_than_8_lines_and_points_to_follow_up(self):
        code, _, err = self.run_lead(["tell", "x__qa"], "line\n" * 9)
        self.assertEqual(code, 2)
        self.assertIn("follow-up", err)
        self.assertEqual(self.rt.sent, [])

    def test_tell_kind_sends_the_template_and_ignores_stdin(self):
        code, _, err = self.run_lead(["tell", "x__qa", "--kind", "compact-the-lead"], "")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rt.sent[0][1],
                         templates.render("from-lead/compact-the-lead", agent_cli=lead_cli.AGENT_CLI))
        self.assertEqual(self.messages()[-1]["kind"], "compact-the-lead")

    # status

    def idle_children(self, *threads):
        self.rt.me["children"] = [{"id": t, "status": "idle", "title": "t"} for t in threads]

    def flagged(self, out, name):
        line = next(l for l in out.splitlines() if l.startswith("&" + name))
        return "idle, sent nothing" in line

    def test_status_shows_every_agent_and_flags_an_idle_one_that_sent_nothing(self):
        self.rt.me["children"] = [{"id": self.build, "status": "idle", "title": "b"},
                                  {"id": self.qa, "status": "active", "title": "q"}]
        self.rt.context = {"used_tokens": 50000, "window": 200000}
        code, out, err = self.run_lead(["status"], "")
        self.assertEqual(code, 0, err)
        qa = next(l for l in out.splitlines() if l.startswith("&x__qa"))
        self.assertIn("idle", next(l for l in out.splitlines() if l.startswith("&x__build")))
        self.assertTrue(self.flagged(out, "x__build"))
        self.assertIn("active", qa)
        self.assertFalse(self.flagged(out, "x__qa"))
        self.assertIn("Lead context: 50000 of 200000 tokens (25%)", out)

    def test_status_does_not_flag_an_agent_that_sent_its_done_message(self):
        self.idle_children(self.build)
        teamlib.append_message(self.root, {"from": "x__build", "to": "lead", "kind": "done",
                                           "first": "PASS", "delivery": "queued"})
        code, out, _ = self.run_lead(["status", "x__build"], "")
        self.assertEqual(code, 0)
        self.assertFalse(self.flagged(out, "x__build"))
        self.assertIn("done PASS", out)
        self.assertNotIn("x__qa", out)

    def test_a_hand_off_to_a_peer_clears_the_flag(self):
        self.idle_children(self.build)
        teamlib.append_message(self.root, {"from": "x__build", "to": "x__qa", "kind": "ready-for-qa",
                                           "first": "ready for QA", "delivery": "queued"})
        _, out, _ = self.run_lead(["status", "x__build"], "")
        self.assertFalse(self.flagged(out, "x__build"))
        self.assertIn("to x__qa: ready-for-qa", out)

    def test_a_failed_or_unconfirmed_send_does_not_clear_the_flag(self):
        self.idle_children(self.build)
        for delivery in ("failed", "unconfirmed"):
            teamlib.append_message(self.root, {"from": "x__build", "to": "lead", "kind": "done",
                                               "first": "PASS", "delivery": delivery})
            _, out, _ = self.run_lead(["status", "x__build"], "")
            self.assertTrue(self.flagged(out, "x__build"), delivery)

    def test_a_follow_up_makes_an_idle_agent_owe_a_new_message(self):
        self.idle_children(self.build)
        teamlib.append_message(self.root, {"from": "x__build", "to": "lead", "kind": "done", "first": "PASS"})
        record = {"from": "lead", "to": "x__build", "kind": "follow-up", "time": "2999-01-01T00:00:00Z"}
        with open(teamlib.messages_path(self.root), "a") as f:
            f.write(__import__("json").dumps(record) + "\n")
        _, out, _ = self.run_lead(["status", "x__build"], "")
        self.assertTrue(self.flagged(out, "x__build"))

    def test_status_lists_a_child_thread_that_is_not_registered(self):
        self.rt.me["children"] = [{"id": self.build, "status": "idle", "title": "b"},
                                  {"id": "thr_stray", "status": "active", "title": "&stray"}]
        _, out, _ = self.run_lead(["status"], "")
        stray = next(l for l in out.splitlines() if l.startswith("(not registered)"))
        self.assertIn("thr_stray", stray)
        self.assertIn("active", stray)
        _, one, _ = self.run_lead(["status", "x__build"], "")
        self.assertNotIn("thr_stray", one)

    def test_status_asks_bb_about_an_agent_the_children_list_misses(self):
        self.rt.shown_threads[self.build] = "env_lead"
        _, out, _ = self.run_lead(["status", "x__build"], "")
        self.assertIn(("show", self.build), self.rt.calls)
        self.assertIn("idle", out)

    # show, output, log

    def test_show_output_and_log_turn_the_name_into_a_thread(self):
        for verb in ("show", "output", "log"):
            code, _, err = self.run_lead([verb, "x__qa"], "")
            self.assertEqual(code, 0, err)
        self.assertIn(("output", self.qa), self.rt.calls)
        self.assertIn(("log", self.qa, False), self.rt.calls)
        self.assertIn(("show", self.qa), self.rt.calls)
        self.run_lead(["log", "x__qa", "--all"], "")
        self.assertIn(("log", self.qa, True), self.rt.calls)
        self.assertEqual(self.run_lead(["show", "nobody"], "")[0], 2)

    # wait

    def test_wait_maps_the_exit_codes_to_words(self):
        for exit_code, word in ((0, "idle"), (2, "timeout"), (4, "errored")):
            self.rt.wait_result = {"matched": exit_code == 0, "exit": exit_code}
            code, out, _ = self.run_lead(["wait", "x__build", "--timeout", "5m"], "")
            self.assertEqual(code, exit_code)
            self.assertIn(word, out)
        self.assertIn(("wait", self.build, "5m"), self.rt.calls)
        self.assertIn("moe-lead.py log x__build", out)

    # retry

    def test_retry_refuses_the_fourth_time_and_a_message_from_the_agent_resets_it(self):
        for i in range(3):
            code, out, err = self.run_lead(["retry", "x__build"], "")
            self.assertEqual(code, 0, err)
            self.assertIn("retry %d of 3" % (i + 1), out)
        code, _, err = self.run_lead(["retry", "x__build"], "")
        self.assertEqual(code, 1)
        self.assertIn("tell the user", err)
        self.assertEqual([c for c in self.rt.calls if c[0] == "retry"], [("retry", self.build)] * 3)
        self.assertEqual(self.run_lead(["retry", "x__qa"], "")[0], 0)  # counted per agent
        teamlib.append_message(self.root, {"from": "x__build", "to": "lead", "kind": "tell-lead"})
        self.assertEqual(self.run_lead(["retry", "x__build"], "")[0], 0)

    # compact, stop

    def test_compact_and_stop_turn_the_name_into_a_thread(self):
        self.assertEqual(self.run_lead(["compact", "x__qa"], "")[0], 0)
        self.assertEqual(self.run_lead(["stop", "x__qa"], "")[0], 0)
        self.assertIn(("compact", self.qa), self.rt.calls)
        self.assertIn(("stop", self.qa), self.rt.calls)

    def test_agent_verbs_refuse_from_a_thread_that_is_not_the_lead(self):
        other = FakeRuntime(thread="thr_other", storage=self.root)
        for argv in (["status"], ["retry", "x__qa"], ["stop", "x__qa"], ["wait", "x__qa"],
                     ["tell", "x__qa", "--kind", "compact-the-lead"]):
            code, _, err = self.run_lead(argv, "", rt=other)
            self.assertEqual(code, 2, argv)
            self.assertIn("not the Lead", err)


class ModelsTest(LeadTest):
    def models(self, rt=None):
        return self.run_lead(["models"], "", rt=rt or self.rt)

    def test_picks_the_default_provider_when_it_is_available(self):
        self.rt.default = "codex"
        self.rt.provider_list = [{"id": "codex", "available": True}, {"id": "claude-code", "available": True}]
        self.rt.model_list = [{"id": "m1", "name": "M One", "description": "d", "is_default": True,
                               "efforts": ["low", "high"]},
                              {"id": "m2", "name": "M Two", "description": "", "is_default": False,
                               "efforts": ["low"]}]
        code, out, err = self.models()
        self.assertEqual(code, 0, err)
        self.assertIn("provider: codex (the user's default)", out)
        self.assertIn(("models", "codex", "proj_1"), self.rt.calls)
        m1 = next(l for l in out.splitlines() if l.startswith("m1"))
        m2 = next(l for l in out.splitlines() if l.startswith("m2"))
        self.assertEqual(m1.split()[:5], ["m1", "M", "One", "yes", "yes"])  # default, lists high
        self.assertEqual(m2.split(), ["m2", "M", "Two", "no"])
        self.assertIn("--provider codex", out)

    def test_falls_back_to_the_leads_own_provider_when_the_default_is_unavailable_or_unset(self):
        self.rt.default = "codex"
        self.rt.provider_list = [{"id": "codex", "available": False}]
        code, out, _ = self.models()
        self.assertIn("provider: claude-code (this thread's own", out)
        self.assertIn("codex, is not available", out)
        self.rt.default = None
        _, out, _ = self.models()
        self.assertIn("no default provider", out)
        self.assertIn(("models", "claude-code", "proj_1"), self.rt.calls)


class RuntimeModelsTest(unittest.TestCase):
    """BbRuntime.models() normalises bb's model list (the keys `moe-lead.py models` reads)."""

    def test_is_default_and_effort_names_come_from_bb_objects_or_strings(self):
        from moelib.runtime import BbRuntime
        rt = BbRuntime(cli="unused")
        rt._json = lambda args, stdin=None: [
            {"id": "a", "displayName": "A", "description": "d", "isDefault": True,
             "supportedReasoningEfforts": [{"reasoningEffort": "low", "description": "x"},
                                           {"reasoningEffort": "high", "description": "y"}]},
            {"id": "b", "displayName": "B", "supportedReasoningEfforts": ["medium"]},
            {"id": "c", "displayName": "C"}]
        a, b, c = rt.models("p", "proj")
        self.assertEqual((a["is_default"], a["efforts"], a["name"], a["description"]),
                         (True, ["low", "high"], "A", "d"))
        self.assertEqual((b["is_default"], b["efforts"]), (False, ["medium"]))
        self.assertEqual((c["is_default"], c["efforts"]), (False, []))


def messaging_sleep():
    """Silence the 1 s retry pause of moelib.messaging in a test; returns the undo."""
    from moelib import messaging
    saved = messaging.time.sleep
    messaging.time.sleep = lambda s: None
    return lambda: setattr(messaging.time, "sleep", saved)


class TitleTest(LeadTest):
    def test_title_alone_sets_the_title_and_needs_no_team_file(self):
        code, out, err = self.run_lead(["setup", "--title", "🧾 CSV export"], "")
        self.assertEqual(code, 0, err)
        self.assertIn(("set_title", "🧾 CSV export"), self.rt.calls)
        self.assertIsNone(self.team())

    def test_title_with_the_tier_map_is_set_after_the_file_is_written(self):
        code, _, err = self.run_lead(SETUP + ["--title", "T"], "")
        self.assertEqual(code, 0, err)
        self.assertIn(("set_title", "T"), self.rt.calls)
        self.assertIsNotNone(self.team())

    def test_a_failed_setup_does_not_set_the_title(self):
        code, _, _ = self.run_lead(["setup", "--provider", "p", "--title", "T"], "")
        self.assertEqual(code, 2)
        self.assertNotIn(("set_title", "T"), self.rt.calls)


if __name__ == "__main__":
    unittest.main()
