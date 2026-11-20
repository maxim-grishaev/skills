# Asking the user

Any agent that asks the user a decision follows this file. Your role file may add to it, or require the full session; otherwise it never contradicts it.

## Rules for every ask

- Answer facts from the code and docs yourself. Ask the user only decisions.
- Ask in plain markdown, not with the ask-user tool (`AskUserQuestion`). This holds for every asking message.
- Ask every ambiguous point that changes what you deliver. Stay at topic level: no detail sub-questions, no cap on the count.
- Format each question by the template below, with numbered choices and your recommendation first.
- Word each question so "yes"/"y"/"ok" accepts your recommendation. The user answers with a choice number, free text, or both.
- Before an asking message, run `moe-agent.py wait-user '<what>'` (the Lead: `moe-lead.py wait-user '<what>'`), for example `wait-user 'Q3 - model tier'`. It puts ❓ in front of your thread's title, pushes one notification that opens your thread, and prints the line to end on.
- End every asking message with the line it prints, `waiting for user on <what>`, then stop.

## Marker and notification

- ❓ means you wait on the user's answer to a question. One `wait-user` call per asking message; in a full session the ❓ stays on between questions.
- ❗️ means the user must do something that is not answering a question: supply credentials, allow a refused permission, lift a blocker only they can lift, take a step outside bb. Run `wait-user --act '<what>'`. Name the step in the message, then end on the same line. A choice the user picks from is a question: ❓.
- A thread carries one marker: a new `wait-user` replaces the old one.
- The user's answer arrives: if you ask again at once, just ask. If nothing stays open, run `user-answered` first, before anything else. It takes the marker off and leaves the rest of the title. Nothing does this for you.
- The user may act while your turn is still running, for example in the form a `bb secret request` shows. No new turn starts then: run `user-answered` as soon as the command returns.
- A `warning:` from the script is not a stop. Carry on and end on the line.
- bb's own approval prompts need none of this: bb already notifies for them.

## Question template

```
❓ Q<n> - <title>: <what you know, then the choices>

➡️ 1. <your recommended answer>

2. <second answer>

n. <n-th answer>
```

Put a blank line after the question line and between choices, as shown. bb's Markdown renderer joins lines that a single newline separates, so without blank lines the choices show as one paragraph.

## Simple or full

Genuine ambiguity: you cannot pick the answer with confidence, and the choices lead to different work.

- **Full session:** two or more questions, and genuine ambiguity. Both must hold. Follow "Full session" below.
- **Simple case:** one question, or no genuine ambiguity. Send the question in the format above, end with the waiting line, and go on with the answer. There is no understanding sync.

## Full session

- Sort by impact and risk, biggest first. A question that depends on an open one waits behind it.
- Send one question per message, never a round.
- After each answer, fold it in and send the next question at once. An answer that opens a new point adds a question to the queue, sorted like the rest. The user follows up on an earlier question on their own when they want to.
- After the last answer, send one message with every question and its answer. Ask: "Did I get it right?" End it with `waiting for user on the sync`.
- A correction re-opens that point only. Ask it again, then send a short re-sync.
- Go on with your work only after the user confirms.

## Group small questions

Your role file may let you group several small, independent questions in one message. Use the same ❓/➡️ format for each, and end with one `waiting for user on <what>` line for the block. Without that permission, ask one question per message.
