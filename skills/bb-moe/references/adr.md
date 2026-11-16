# ADRs

An ADR (architecture decision record) lives in `S/design/adr/NNNN-<slug>.md`. `S` is the storage root, written out as an absolute path.

An ADR records one decision. Write one only when at least one holds:

- The decision is hard to reverse.
- It crosses topics, so several agents build on it.
- The user chose between real alternatives.

Not for every choice. A light job has none: stop and tell the Lead about a decision that needs one. The Lead asks the user, who may resolve it or move the job to full. `&architect` writes most ADRs. In a full job, another agent that makes such a decision later (usually a builder) drafts the ADR with status "proposed" and sends it to `&architect` to discuss. The architect has the final word: it accepts, edits or rejects the ADR and sets its status. The drafting agent follows the architect's version. Number ADRs in order: `0001-<slug>.md`. If the project keeps its own ADRs, follow its format; write into the repo only if the user allowed it.

```markdown
# <NNNN>. <decision in one line> (<date>)

Status: <proposed by <agent> / accepted by <the user, the Lead or &architect> / rejected by &architect / superseded by NNNN>

## Context
<What forces the decision. Facts, marked seen or inferred.>

## Decision
<What we do.>

## Rejected alternatives
- <option>: <why not>

## Consequences
<What gets easier, what gets harder, what to watch.>
```
