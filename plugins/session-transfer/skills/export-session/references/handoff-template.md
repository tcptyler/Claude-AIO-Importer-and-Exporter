# Handoff brief templates

Write both files in the brief folder. Use plain, specific language. The reader is another Claude that will read this before the transcript and must be able to continue the work without asking the user to repeat anything.

## HANDOFF.md

```markdown
# Handoff: <conversation title>

Exported <date> from <claude.ai chat | Cowork task | Claude Code session>. Written by Claude for the Claude that continues this work.

## In one paragraph
What this conversation is about, why the user started it, and what it has produced so far.

## The user
- Who they are and what they do, as relevant to this work.
- How they like to work and be answered (length, tone, formatting, things they dislike), with the evidence from this chat.

## Goal and definition of done
- The outcome the user wants.
- What "finished" looks like, and any constraints (budget, deadline, tools, platforms).

## Where we are now
- Done: completed pieces, with file or artifact names.
- In progress: the exact state of anything half-finished.
- Next step: the single next thing to do, specific enough to start immediately.

## Decisions and why
- Each decision, the reason, and options that were considered and rejected.

## Key facts and details
- Names, numbers, URLs, file names, versions, settings, quotes the user cares about. No secrets.

## Files, artifacts and images
- Each important file or artifact: name, purpose, latest version, status.
- Each important image: what it shows and why it mattered.

## Open questions and promises
- Questions waiting on the user, and anything you said you would do later.

## Gotchas
- What went wrong or was confusing, and how it was resolved, so it isn't repeated.

## How to resume
- What to say first, and what to confirm with the user before continuing.
```

## MEMORY.md

```markdown
# Memory and instructions in effect

Copied verbatim from what was visible in this conversation's context. Sections that weren't visible say so.

## Account memory
<verbatim, or "Not visible in this conversation">

## User preferences and style
<verbatim>

## Project instructions
<verbatim, if this chat is in a project>

## CLAUDE.md / workspace instructions
<verbatim, for Claude Code and Cowork>

## Learned in this conversation (not yet in memory)
- Durable facts about the user or their work that came up here and would be worth remembering.
```
