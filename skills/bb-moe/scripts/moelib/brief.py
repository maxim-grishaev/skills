"""Brief assembly for `moe-lead.py brief`: validate the flags, resolve tier, model and
environment by role, render the brief from templates/brief/, save it.

The brief's layout and every sentence come from templates/brief/. The code supplies
values, among them short phrases that fill one slot of a sentence ("yes, plain", "none").
"""

import os
import re
import subprocess

from moelib import team as teamlib
from moelib import templates
from moelib.runtime import BbError
from moelib.util import Failure

REFERENCES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "references"
)

# role: (role file, tier, environment, read-only, role in one line)
# Mirrors references/brief-template.md, "Roles".
ROLES = {
    "debrief": ("debrief.md", "stronger", "lead", True, "the debrief analyst"),
    "scout": ("scout.md", "mid", "lead", True, "the scout"),
    "architect": ("architect.md", "stronger", "lead", False, "the architect"),
    "arch-skeptic": ("arch-skeptic.md", "stronger", "lead", True, "the arch skeptic"),
    "build": ("build.md", "mid", "new-worktree", False, "the builder"),
    "qa": ("qa.md", "mid", "builder", False, "the QA gate"),
    "reviewer": ("reviewer.md", "stronger", "builder", True, "the reviewer"),
    "review-skeptic": ("review-skeptic.md", "stronger", "builder", True, "the review-skeptic"),
    "main-qa": ("main-qa.md", "mid", "lead", False, "the work branch's QA gate"),
    "butler": ("butler.md", "mid", "lead", False, "the Lead's scout and integrator"),
    "delivery": ("delivery.md", "mid", "new-worktree", False, "the deliverable builder"),
    "custom": (None, None, None, False, None),
}
TIERS = ("stronger", "mid")
WEIGHTS = ("full", "light")
PERMISSION_MODES = ("accept-edits", "auto", "full")
NO_WEIGHT = "not set yet; the Lead sets it after the debrief"
NOT_SPAWNED = "not spawned yet"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(__[a-z0-9][a-z0-9-]*)?$")


def slugify(text):
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return "-".join(words[:6])[:40].strip("-") or "task"


def resolve_commit(worktree, ref):
    p = subprocess.run(["git", "-C", worktree, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def prepare(args, runtime, root, team, me, body, agent_cli):
    """Validate `args` and render the brief. Returns a plan dict; raises Failure listing every
    bad flag at once. Nothing is written here."""
    errors = []
    for flag in ("name", "role", "task"):
        if not getattr(args, flag):
            errors.append("--%s is required" % flag)
    checks = (("role", list(ROLES)), ("tier", TIERS), ("commit", ("no", "yes")), ("push", ("no", "yes")))
    for flag, allowed in checks:
        value = getattr(args, flag)
        if value is not None and value not in allowed:
            errors.append("--%s %s: use one of %s" % (flag, value, ", ".join(allowed)))
            setattr(args, flag, None)
    name = (args.name or "")
    task = args.task or ""

    lead = team.get("lead", {})
    tiers = team.get("tiers", {})
    agents = team.get("agents", {})

    # name
    if name.startswith("&"):
        errors.append("--name %s: give the name without '&'; the script adds it" % name)
        name = name.lstrip("&")
    if name and not NAME_RE.match(name):
        errors.append("--name %s: use <topic>__<role> or a bare role, lowercase kebab-case" % name)
    registered = name in agents
    if registered and not args.replace:
        errors.append("&%s is already registered (thread %s): send a follow-up brief with "
                      "`bb thread tell %s --mode queue --message-file <brief>`; use --replace only "
                      "for a crashed thread the user allowed to replace"
                      % (name, agents[name].get("thread"), agents[name].get("thread")))
    if args.replace and not registered:
        errors.append("--replace: &%s is not registered" % name)

    role_file, role_tier, role_env, read_only, what = ROLES.get(args.role) or (None, None, None, False, "")
    if args.role == "custom":
        for flag in ("what", "tier", "env"):
            if not getattr(args, flag):
                errors.append("--role custom needs --%s" % flag)
    what = args.what or what

    if args.role == "scout" and not args.works_for:
        errors.append("--role scout needs --works-for <agent>")
    if args.works_for and args.works_for.startswith("&"):
        errors.append("--works-for %s: give the name without '&'" % args.works_for)

    # tier and model
    tier = args.tier or role_tier
    model = None
    if not tiers.get("provider"):
        errors.append("no provider in the tier map: run `moe-lead.py setup --provider ...`")
    if tier:
        model = tiers.get(tier)
        if not model:
            errors.append("no %s model in the tier map: run `moe-lead.py setup --%s <model id>`" % (tier, tier))

    # environment
    env = args.env or role_env
    if env == "builder":
        if "__" in name:
            env = "of:%s__build" % name.split("__")[0]
        else:
            errors.append("--env: no topic in --name %s to find its builder; give --env of:<agent>" % name)
            env = None
    spec_env = {}
    where = None
    if env == "lead":
        if not lead.get("environment"):
            errors.append("no Lead environment in %s: run `moe-lead.py setup`" % teamlib.team_path(root))
        else:
            spec_env = {"environment": lead["environment"]}
            where = templates.render("brief/where-lead", worktree=lead.get("worktree"),
                                     branch=lead.get("branch"))
    elif env == "new-worktree":
        if not lead.get("isGitRepo"):
            errors.append("--env new-worktree: the Lead's environment is not a git repo")
        else:
            ref = args.base or "HEAD"
            sha = resolve_commit(lead["worktree"], ref)
            if not sha:
                errors.append("--base %s: not a commit in %s" % (ref, lead["worktree"]))
            else:
                spec_env = {"new_worktree_base": sha}
                where = templates.render("brief/where-new-worktree", commit=sha,
                                         base="the Lead's HEAD" if not args.base else args.base)
    elif env and env.startswith("of:"):
        owner = env[3:].lstrip("&")
        entry = agents.get(owner)
        if not entry or not entry.get("environment"):
            errors.append("--env %s: &%s is not registered with an environment" % (env, owner))
        else:
            try:
                path = runtime.environment_path(entry["environment"])
            except BbError:
                path = None
            spec_env = {"environment": entry["environment"]}
            where = templates.render("brief/where-of-agent", owner=owner,
                                     path="`%s`" % path if path else "(path not available)",
                                     environment=entry["environment"])
    elif env:
        errors.append("--env %s: use lead, new-worktree or of:<agent>" % env)
    if args.base and env != "new-worktree":
        errors.append("--base: only with --env new-worktree")
    if where and read_only:
        where += " " + templates.render("brief/read-only")

    # limits
    if args.push == "yes" and args.role != "butler":
        errors.append("--push yes: only &butler pushes")
    if args.creds and not os.path.isfile(args.creds):
        errors.append("--creds %s: no such file" % args.creds)

    # peers
    peers = []
    for peer in [p.strip() for p in (args.peers or "").split(",") if p.strip()]:
        if peer.startswith("&"):
            errors.append("--peers %s: give names without '&'" % peer)
            peer = peer.lstrip("&")
        if not NAME_RE.match(peer):
            errors.append("--peers %s: not an agent name" % peer)
        peers.append(peer)

    if args.spawn and not me.get("project"):
        errors.append("--spawn: the project is unknown (no project in `bb status`)")

    if errors:
        raise Failure(errors, header="error: nothing written or spawned")

    # render
    lead_id = lead.get("thread")
    files = "`%s/roles/common.md`" % REFERENCES
    if role_file:
        files += " and `%s/roles/%s`" % (REFERENCES, role_file)
    opening = templates.render(
        "brief/opening", agent_name=name, what=what, task=task, lead_id=lead_id, agent_cli=agent_cli,
        files=files, root_path=root, weight=team.get("weight") or NO_WEIGHT)
    limits = templates.render(
        "brief/limits", start=args.start or "nothing",
        commit="yes, on your branch" if args.commit == "yes" else "no",
        push="yes, plain" if args.push == "yes" else "no",
        creds="`%s`" % args.creds if args.creds else "none")

    def thread_of(agent):
        tid = agents.get(agent, {}).get("thread")
        return "`%s`" % tid if tid else NOT_SPAWNED

    members = []
    if args.works_for:
        boss = args.works_for.lstrip("&")
        members.append(templates.render("brief/team-works-for", boss=boss, thread=thread_of(boss)))
    for peer in peers:
        members.append(templates.render("brief/team-peer", peer=peer, thread=thread_of(peer)))
    team_text = templates.render(
        "brief/team", lead_id=lead_id, team_file=teamlib.team_path(root),
        members="".join(m + "\n" for m in members))
    text = templates.render(
        "brief/brief", opening=opening, body=body, where=where, limits=limits, team=team_text) + "\n"

    spec = dict(spec_env, project=me["project"], title=args.title or "&" + name,
                provider=tiers["provider"], model=model)
    if args.permission_mode:
        spec["permission_mode"] = args.permission_mode
    return {
        "name": name, "task": task, "role": args.role, "model": model, "text": text, "spec": spec,
        "registered": registered, "works_for": args.works_for.lstrip("&") if args.works_for else None,
        "replaces": agents[name].get("thread") if registered else None,
    }


def save(root, plan):
    """Write the brief to S/briefs/<name>-NN-<task>.md and return the path. Drafts of an
    unspawned agent are overwritten; a registered agent's briefs are numbered on."""
    name = plan["name"]
    briefs = os.path.join(root, "briefs")
    os.makedirs(briefs, exist_ok=True)
    if plan["registered"]:
        numbers = [int(m.group(1)) for f in os.listdir(briefs)
                   for m in [re.match(re.escape(name) + r"-(\d+)-", f)] if m]
        nn = max(numbers, default=0) + 1
    else:
        nn = 1
    path = os.path.join(briefs, "%s-%02d-%s.md" % (name, nn, slugify(plan["task"])))
    with open(path, "w") as f:
        f.write(plan["text"])
    return path
