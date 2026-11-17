# claude-session-bundle format (version 1)

A bundle is a zip named `<title>-<YYYYMMDD-HHMM>.session.zip`.

```
manifest.json              format, source, counts, warnings, and every file with bytes + sha256
README.md                  what this is and how to import it
brief/HANDOFF.md           handoff brief written by Claude at export time (optional)
brief/MEMORY.md            memory, preferences and instructions Claude was using (optional)
transcript/transcript.md   the full current branch, one "### [NNNN] Who · time" header per message
images/                    pasted / uploaded images and tool screenshots: m<msg>-<k>-<name>.<ext>
attachments/               uploaded documents and extracted or pasted text: m<msg>-<name>
artifacts/<slug>/vNNN.ext  every version of every artifact; latest.ext is the final state
files/uploads/             the chat or task workspace uploads (originals)
files/outputs/             files Claude created in the workspace
files/edited/              files a Claude Code / Cowork session created or edited (current content)
memory/                    CLAUDE.md instruction files and Claude Code auto-memory (local sessions)
project/                   claude.ai project instructions and knowledge (when the chat is in a project)
raw/                       source data exactly as captured (conversation.json, session .jsonl, ...)
```

## manifest.json

```json
{
  "format": "claude-session-bundle",
  "version": 1,
  "created_by": "session-transfer 1.0.0",
  "exported_at": "2026-11-13T01:00:00Z",
  "source": {"source": "claude.ai | claude-code | cowork | claude.ai-sandbox", "title": "...",
             "conversation_id": "...", "model": "...", "created_at": "...", "updated_at": "..."},
  "counts": {"messages": 0, "images": 0, "attachments": 0, "artifacts": 0, "...": 0},
  "warnings": ["anything that could not be captured"],
  "files": [{"path": "images/m0003-1-photo.png", "bytes": 1234, "sha256": "...", "role": "image", "message": 3}]
}
```

`manifest.json` does not list itself.

## Transcript conventions

- Header per message: `### [0007] Claude · 2026-11-10 14:04 UTC` (User, Claude, System event, Context summary).
- Images: `![name](../images/...)`. Attachments: `> Attachment: [name](../attachments/...)`.
- Artifacts: `> Artifact create v1: "Title" -> [artifacts/title/v001.html](../artifacts/title/v001.html)`.
- Tool calls and results are summarized on one line: `> Tool · name: summary`, `> Result: ...`.
- Claude's private reasoning is not in the transcript; it stays in `raw/`.

## Sources

| Source | Captured by | Notes |
|---|---|---|
| claude.ai chat | `capture.js` (bookmark, console, or Claude in Chrome) | Reads the internal API, so the whole chat is captured even after auto-summarizing. Images come from claude.ai's preview copies unless the original is in the workspace. |
| Claude Code | `export_local.py` | Reads the session `.jsonl`. Exact. Pasted images are embedded in it. |
| Cowork | `export_local.py`, or the task's "Download task data" | Same `.jsonl` format when the transcript is reachable from the task. |
| claude.ai, no browser | `export_local.py --fallback-transcript` | Last resort: sandbox transcripts or a transcript Claude writes from its own context. |
