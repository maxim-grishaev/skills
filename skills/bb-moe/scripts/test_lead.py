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
        files = "`%s/roles/common.md` and `%s/roles/build.md`" % (brieflib.REFERENCES, brieflib.REFERENCES)
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
        self.assertIn("A new worktree from commit `%s` (the Lead's HEAD)" % self.sha, self.brief_text("x__build"))

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
        self.assertIn("`&x__build`'s worktree `/builder/worktree` (environment `env_new1`)", self.brief_text("x__qa"))

    def test_read_only_roles_say_so(self):
        self.brief("--name", "x__reviewer", "--role", "reviewer", "--task", "t", "--env", "lead")
        self.assertIn("standing agents. Read-only.", self.brief_text("x__reviewer"))

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


if __name__ == "__main__":
    unittest.main()
