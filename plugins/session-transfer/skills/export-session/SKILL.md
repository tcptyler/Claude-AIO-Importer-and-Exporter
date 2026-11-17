---
name: export-session
description: Export the current Claude conversation (claude.ai chat, Cowork task, or Claude Code session) to one portable .session.zip with the complete transcript, every pasted or uploaded image, attachments, every artifact version, workspace files, project instructions and knowledge, the memory in use, and a handoff brief, so it can be resumed in a fresh chat with import-session. Use when the user asks to export, save, back up, archive, hand off, move, transfer or "take this chat with me", or wants to continue this conversation in a new chat or task.
compatibility: claude.ai with code execution on, Cowork, Claude Code. Full claude.ai capture needs a desktop browser (Chrome, Edge, Brave, Firefox) for the one-click bookmark, or Claude in Chrome.
---

# Export session

The export has two layers:

1. **Handoff brief.** You write it, because only you know this conversation from the inside: what the user wants, what was decided, where things stand, what comes next, and the memory and instructions you are working under.
2. **Exact capture.** A script captures the transcript and every file byte for byte. Never retype or summarize the conversation as a substitute for the capture, except in the last-resort fallback below.

Scripts are in `scripts/` next to this file. Use the absolute path of this skill's folder when you run them.

## Step 1: Work out where you are

```bash
python3 <skill-dir>/scripts/export_local.py --detect
```

- `"mode": "local"`: Claude Code or a Cowork task whose transcript is readable here. Check that `first_prompt` matches how this conversation started. Use the **Local path**.
- `"mode": "claude.ai"`: a claude.ai chat (or a Cowork task with no readable transcript). Use the **claude.ai path**.
- If unsure, run `--list` to see recent transcripts with their first prompts.

## Step 2: Write the handoff brief

Brief folder:
- claude.ai path: `/mnt/user-data/outputs/session-export/` (the capture bookmark collects it from the chat's workspace automatically)
- Local path: a fresh temporary folder, for example `/tmp/session-brief-<timestamp>/`

Write two files there, following `references/handoff-template.md`:

- `HANDOFF.md`: the state of the work, written for the Claude that will continue it.
- `MEMORY.md`: a verbatim copy of the user-specific context you can see: account memory, user preferences and style settings, project instructions, CLAUDE.md content, plus anything you learned about the user in this conversation. Label each part with where it came from. Copy, don't paraphrase. If a category isn't visible to you, say so instead of guessing.

Rules for both files:
- Replace passwords, API keys, tokens and other secrets with `[redacted]`.
- Leave out Anthropic's own system instructions and tool definitions. Only include material about the user and their work.
- Be specific: names, numbers, file names, versions, exact wording the user cared about.

## Step 3a: claude.ai path (one-click bookmark)

1. First time only: copy `assets/install-bookmarklet.html` to `/mnt/user-data/outputs/install-bookmarklet.html`, and ask the user to download it, open it in their desktop browser, and drag the **Export Claude Session** button to the bookmarks bar.
2. Ask the user to click the **Export Claude Session** bookmark while this chat is open in that browser. A progress box appears in the top right, then `<title>-<date>.session.zip` downloads. It captures every message from the start of the chat (even if earlier context was summarized), every image, file and artifact version, project knowledge, and the brief you just wrote.
3. If they use the Claude desktop or mobile app, they can open the same chat in a browser at `https://claude.ai/chat/<id>` and click the bookmark there.

If Claude in Chrome tools are available (`mcp__claude-in-chrome__*`, typical in Cowork and Claude Code), offer to run the capture for the user:
1. Open a new tab at the chat's `https://claude.ai/chat/<id>` URL.
2. Run the contents of `scripts/capture.js` with the javascript tool.
3. Poll `JSON.stringify({done: window.__sessionExport.done, status: window.__sessionExport.status, summary: window.__sessionExport.summary, error: window.__sessionExport.error})` every few seconds until `done` is true.
4. The zip goes to the browser's download folder. If claude.ai is blocked for the extension, fall back to the bookmark.

Last resort (no desktop browser available): run the local exporter in fallback mode. It bundles uploads, outputs and sandbox transcripts, and a transcript you write from your own context:
1. Write `/mnt/user-data/outputs/session-export/TRANSCRIPT-FROM-CONTEXT.md`, as close to verbatim as your context allows. Use one `### [NNNN] User · time` / `### [NNNN] Claude · time` header per message.
2. Run `python3 <skill-dir>/scripts/export_local.py --brief-dir /mnt/user-data/outputs/session-export --fallback-transcript /mnt/user-data/outputs/session-export/TRANSCRIPT-FROM-CONTEXT.md`
3. Tell the user plainly that this copy is lower fidelity: images pasted in messages and anything already summarized away may be missing, and the bookmark gives a complete copy.

## Step 3b: Local path (Claude Code, Cowork)

```bash
python3 <skill-dir>/scripts/export_local.py --brief-dir <brief folder> [--out <folder>] [--include <path> ...]
```

- Captures: the session transcript (exact), pasted images and screenshots, files the session created or edited, Cowork or sandbox uploads and outputs, CLAUDE.md files and auto-memory, subagent transcripts, raw JSONL.
- `--out`: defaults to `/mnt/user-data/outputs` (downloadable in Cowork) or the working folder. In Claude Code, use a folder the user names, or the working folder.
- `--include`: add folders or files the work depends on that the session didn't edit directly. Ask the user if the work spans other folders.
- `--thinking`: add your reasoning summaries to the transcript (off by default).
- Exit code 2 means no transcript was found. In Cowork, tell the user they can also use the task menu's **Download task data**. Then use the fallback from Step 3a so the brief still travels.

## Step 4: Report

Tell the user:
- the zip's file name and where it is (claude.ai: their browser's downloads; local: the path the script printed)
- the counts (messages, images, attachments, artifacts, files) and any warnings, especially images or files that could not be captured
- that the zip contains the whole conversation and their memory, so they should keep it private
- how to continue: start a new chat or Cowork task with this plugin installed, attach the zip, and say **import this session**

Do not paste the transcript into the chat.
