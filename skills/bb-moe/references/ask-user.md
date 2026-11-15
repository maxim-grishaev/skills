# Asking the user

Any agent that asks the user a decision follows this file. Your role file may add to it, but never contradicts it. `R` is the skill's `references/` directory; this file is `R/ask-user.md`.

## Rules

- Answer facts from the code and docs yourself. Ask the user only decisions.
- Ask in plain markdown, not with the ask-user tool (`AskUserQuestion`). This holds for every asking message: a single question, the sync and a grouped block.
- Ask every ambiguous point that changes what you deliver. Stay at topic level: no detail sub-questions, no cap on the count.
- Sort by impact and risk, biggest first. A question that depends on an open one waits behind it.
- Send one question per message, never a round. Use this format, with numbered choices:

  ```
  ❓ Q<n> - <title>: <what you know, then the choices>
  ➡️ <your recommended answer>
  ```

- Word each question so "yes" accepts your recommendation. The user answers with a choice number, free text, or both.
- End every asking message with a line `waiting for user on <what>` (for example `waiting for user on Q3`), then stop.
- The answer was a plain choice? Ask the next question. It was free text or opened a new point? Ask "Move on, or follow up on Q<n>?" first.

## Group small questions

Your role file may let you group several small, independent questions in one message. Then use the same ❓/➡️ format for each, and end with one `waiting for user on <what>` line for the block. Without that permission, ask one question per message.

## Understanding sync

- After the last answer, send one message with every question and its answer. Ask: "Did I get it right?"
- End it with `waiting for user on the sync`.
- A correction re-opens that point only. Ask it again, then send a short re-sync.
- Go on with your work only after the user confirms.
