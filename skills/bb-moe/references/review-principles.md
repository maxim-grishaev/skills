# Review principles

What `&<topic>__reviewer` looks for, and what `&<topic>__review-skeptic` weighs findings against. Adapted from the `ub-mode` principles: First Make it Work, Then Make it Right, Follow Practice. Here they are questions about a diff.

Review high-level only. Naming, formatting and the style the linter owns are not findings.

Each finding names the principle it rests on. The skeptic then tests the claim, not the taste.

## Make it work

- **One decision, one place.** Is a rule, constant or mapping now decided in two places that can drift apart?
- **Smallest edit.** Does the diff carry changes the task did not need, such as drive-by refactors or speculative options?
- **Data shape first.** Does the logic fight a data shape that should have changed instead?
- **Redesign, don't bolt on.** Was a new requirement wedged into a design that no longer fits? Would a design built for it from the start be simpler?
- **Subtract before adding.** Could removing complexity give the same result as adding a layer, flag or branch?
- **Illegal states impossible.** Can the new types hold a combination that must never happen? Examples: two flags that exclude each other; an optional field that one state requires.
- **Boundaries.** Is outside data (requests, files, env, third-party responses) checked once, where it enters? Is it trusted inside? Validation scattered through the core, or missing at the edge, is a finding.
- **Pure core.** Is business logic mixed with I/O where a pure function would do?
- **Type system.** Is the compiler silenced (casts, `any`, ignores, non-null assertions)? Would a better type make the wrong value impossible to write?
- **Idempotent operations.** An operation can be retried, or stop halfway. Does running it twice end in a different state?
- **Shared mutable state.** Do concurrent writers share something they do not need? If they must share, is there exactly one writer, enforced by the structure?

## Make it right

- **Root cause.** Does a fix hide a crash with a guard, a retry or a default, instead of fixing the cause?
- **Tests check behaviour.** Do tests call the code the way its user does? Do they check what that user would see? A test that still passes when every function returns nothing is a finding.
- **Coverage of risk.** Is the new branch that can fail covered? Is the trivial one left alone?
- **Complexity.** Is a new function too complex to follow or test: long, deeply nested, many branches?
- **Duplication.** Is logic copied where one shared piece would do?
- **Tools.** Does the project have complexity, duplication or mutation-testing tools? Then use them and quote their numbers.
- **Dead code.** Is something left that nothing calls any more?
- **Refactor kept behaviour.** Where the diff restructures, is there proof that behaviour did not change? For example: tests pinned before, still green after.

## Practice

- **Commits.** Are they small and ordered? Does each say why, what changed, and how it was proved?
- **Security.** Injection; secrets in code or logs; missing authorisation on a new path.
- **Performance.** Queries in loops; unbounded reads; work repeated per request that could run once.

## Severity

- **Blocking:** wrong or unsafe behaviour, or a structure the next task builds on that is costly to undo. Examples:
  - a hidden root cause;
  - a reachable illegal state;
  - untrusted data in the core;
  - a retry path that is not idempotent;
  - a security risk;
  - a test that proves nothing.
- **Follow-up:** worth doing, safe to land without. Examples: duplication, complexity, a better split, dead code.
