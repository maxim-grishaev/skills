# skills

My agent skills. Install with the open [`skills`](https://github.com/vercel-labs/skills) CLI:

```sh
npx -y skills add maxim-grishaev/skills
```

It asks which skills and which agents (Claude Code, Codex, Cursor, ...) to install them into. Add `-g` to install for
your user instead of the current project.

| Skill | What it does |
| --- | --- |
| `bb-moe` | A lead agent runs a job in [bb](https://getbb.app) with named expert agents as sub-threads. |

## Claude Code plugin

`.claude-plugin/marketplace.json` makes the same `skills/` folder a Claude Code marketplace as well, with one plugin
`mg` whose root is this repo. New skill folders are picked up with no change to it.

```sh
claude plugin marketplace add maxim-grishaev/skills
claude plugin install mg@mg-skills
```

The skill then shows up as `mg:bb-moe`.
Validate: `claude plugin validate .`
