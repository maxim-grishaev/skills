import os
import shutil
import tempfile
import unittest

from fake_runtime import FakeRuntime, load_script, make_git_repo, run_cli
from moelib import team as teamlib
from moelib import templates
from moelib.brief import ROLES


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        os.makedirs(os.path.join(self.dir.name, "g"))

    def write(self, name, text):
        with open(os.path.join(self.dir.name, "g", name + ".md"), "w") as f:
            f.write(text)

    def test_renders_variables(self):
        self.write("a", "Hello ${who}, from ${where}.\n")
        self.assertEqual(templates.render("g/a", root=self.dir.name, who="you", where="here"),
                         "Hello you, from here.")

    def test_missing_variable_names_file_and_variable(self):
        self.write("a", "Hello ${who}, from ${where}.\n")
        with self.assertRaises(templates.TemplateError) as c:
            templates.render("g/a", root=self.dir.name, who="you")
        message = str(c.exception)
        self.assertIn(os.path.join("g", "a.md"), message)
        self.assertIn("missing variable where", message)

    def test_unused_variable_names_file_and_variable(self):
        self.write("a", "Hello ${who}.\n")
        with self.assertRaises(templates.TemplateError) as c:
            templates.render("g/a", root=self.dir.name, who="you", extra="x")
        self.assertIn("unused variable extra", str(c.exception))
        self.assertIn(os.path.join("g", "a.md"), str(c.exception))

    def test_missing_and_unused_reported_together(self):
        self.write("a", "${one} ${two}")
        with self.assertRaises(templates.TemplateError) as c:
            templates.render("g/a", root=self.dir.name, one="1", three="3")
        self.assertIn("missing variable two", str(c.exception))
        self.assertIn("unused variable three", str(c.exception))

    def test_values_are_not_rescanned(self):
        self.write("a", "${body}")
        self.assertEqual(templates.render("g/a", root=self.dir.name, body="costs $5 and ${x}"),
                         "costs $5 and ${x}")

    def test_literal_dollar_is_doubled(self):
        self.write("a", "price $$5 for ${who}")
        self.assertEqual(templates.render("g/a", root=self.dir.name, who="me"), "price $5 for me")

    def test_stray_dollar_is_an_error_naming_the_file(self):
        self.write("a", "price $5")
        with self.assertRaises(templates.TemplateError) as c:
            templates.render("g/a", root=self.dir.name)
        self.assertIn(os.path.join("g", "a.md"), str(c.exception))

    def test_unreadable_template_names_the_file(self):
        with self.assertRaises(templates.TemplateError) as c:
            templates.render("g/none", root=self.dir.name)
        self.assertIn(os.path.join("g", "none.md"), str(c.exception))

    def test_all_refs_lists_groups(self):
        self.write("a", "x")
        self.assertEqual(templates.all_refs(self.dir.name), ["g/a"])


# The groups this file covers. chain/ and lead/ belong to test_agent.py, which makes the same check.
GROUPS = ("brief", "common", "from-lead")


def in_groups(refs):
    return {r for r in refs if r.split("/")[0] in GROUPS}


class ShippedTemplatesTest(unittest.TestCase):
    """Every template file in this file's groups is rendered by a caller with exactly the
    variables it declares: a template with no caller, or a caller out of step, fails here."""

    def test_every_template_renders_through_its_caller(self):
        lead_cli, agent_cli = load_script("moe-lead.py"), load_script("moe-agent.py")
        base = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        root = os.path.join(base, "S")
        make_git_repo(os.path.join(base, "lead"))
        templates.RENDERED.clear()

        lead_rt = FakeRuntime(thread="thr_lead", storage=root)
        lead_rt.shown["environment"]["path"] = os.path.join(base, "lead")
        code, _, err = run_cli(lead_cli, ["setup", "--provider", "p", "--stronger", "s", "--mid", "m"],
                               lead_rt)
        self.assertEqual(code, 0, err)
        for role in ROLES:  # build comes before qa, reviewer and review-skeptic: they join its worktree
            args = ["brief", "--name", "t__" + role, "--role", role, "--task", "check " + role,
                    "--peers", "t__build,t__unspawned", "--spawn"]
            if role == "scout":
                args += ["--works-for", "t__build"]
            if role == "custom":
                args += ["--what", "a custom thing", "--tier", "mid", "--env", "lead"]
            code, _, err = run_cli(lead_cli, args, lead_rt, "body for %s\n" % role)
            self.assertEqual(code, 0, "%s: %s" % (role, err))

        code, _, err = run_cli(lead_cli, ["brief", "--name", "solo", "--role", "butler", "--task", "alone"],
                               lead_rt, "body\n")  # no peers: the team section without members
        self.assertEqual(code, 0, err)
        for argv, body in ((["follow-up", "--name", "t__qa", "--task", "again"], "do it\n"),
                           (["tell", "t__qa"], "short\n"),
                           (["tell", "t__qa", "--kind", "compact-the-lead"], "")):
            code, _, err = run_cli(lead_cli, argv, lead_rt, body)
            self.assertEqual(code, 0, err)

        team = teamlib.load_team(root)
        agent_rt = FakeRuntime(thread=team["agents"]["t__build"]["thread"], parent="thr_lead")
        for argv in (["tell", "t__qa"], ["tell-lead"], ["tell-lead", "--done"]):
            code, _, err = run_cli(agent_cli, argv + ["--root", root], agent_rt, "hello\n")
            self.assertEqual(code, 0, err)

        self.assertEqual(in_groups(templates.RENDERED), in_groups(templates.all_refs()),
                         "templates not rendered by any caller (or rendered but not on disk)")


if __name__ == "__main__":
    unittest.main()
