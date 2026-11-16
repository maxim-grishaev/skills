# Asking the user

Any agent that asks the user a decision follows this file. Your role file may add to it, or require the full session; otherwise it never contradicts it.

## Rules for every ask

- Answer facts from the code and docs yourself. Ask the user only decisions.
- Ask in plain markdown, not with the ask-user tool (`AskUserQuestion`). This holds for every asking message.
- Ask every ambiguous point that changes what you deliver. Stay at topic level: no detail sub-questions, no cap on the count.
- Format each question by the template below, with numbered choices and your recommendation first.
- Word each question so "yes"/"y"/"ok" accepts your recommendation. The user answers with a choice number, free text, or both.
- End every asking message with a line `waiting for user on <what>` (for example `waiting for user on Q3`), then stop.

## Question template

```
❓ Q<n> - <title>: <what you know, then the choices>
➡️ 1. <your recommended answer>
2. <second answer>
3. <third answer>
```

## Simple or full

Genuine ambiguity: you cannot pick the answer with confidence, and the choices lead to different work.

- **Full session:** two or more questions, and genuine ambiguity. Both must hold. Follow "Full session" below.
- **Simple case:** one question, or no genuine ambiguity. Send the question in the format above, end with the waiting line, and go on with the answer. There is no follow-up check and no understanding sync.

## Full session

- Sort by impact and risk, biggest first. A question that depends on an open one waits behind it.
- Send one question per message, never a round.
- The answer was a plain choice? Ask the next question. It was free text or opened a new point? Ask "Move on, or follow up on Q<n>?" first.
- After the last answer, send one message with every question and its answer. Ask: "Did I get it right?" End it with `waiting for user on the sync`.
- A correction re-opens that point only. Ask it again, then send a short re-sync.
- Go on with your work only after the user confirms.

## Group small questions

Your role file may let you group several small, independent questions in one message. Use the same ❓/➡️ format for each, and end with one `waiting for user on <what>` line for the block. Without that permission, ask one question per message.
