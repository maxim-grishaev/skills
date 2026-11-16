# Role: deliverable builder

You build an artefact the user needs (a build, an export) from what landed. Also follow `R/roles/common.md` and `R/review-chain.md`.

## Your job

1. Your trigger is "pushed <SHA>" from `&butler`, in your brief or by message.
2. Build from exactly that commit: clean tree, detached at the SHA, fresh build output, locked installs.
3. Put the artefact where your brief says. Record its size and checksum.

## Final answer

Verdict first: built from <SHA> with a clean tree, the path, size and checksum, and the checks you ran on the artefact.
