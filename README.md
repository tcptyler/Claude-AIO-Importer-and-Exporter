# Claude AIO Importer and Exporter

Move a Claude conversation into a fresh chat without losing anything. **Export** packs a claude.ai chat, Cowork task or Claude Code session into one `.session.zip`. **Import** loads that zip into a new chat or task: Claude verifies it, restores the files, reads the whole conversation, looks at every image, and picks up where you left off.

Everything stays between you and Claude. The export runs in your own browser tab or session, and the zip is saved on your computer. Nothing is uploaded to any other service.

## What the zip contains

| Part | Details |
|---|---|
| Full transcript | Every message from the first to the last, even if Claude auto-summarized the chat |
| Images | Every image pasted inline or uploaded, plus screenshots taken during the session |
| Attachments | Uploaded documents (PDFs and others) and pasted text |
| Artifacts | Every version of every artifact, plus the final version |
| Files | The chat or task workspace: your uploads, files Claude created, files edited in Cowork or Claude Code |
| Project | Project instructions and knowledge files, when the chat lives in a claude.ai project |
| Memory | The memory, preferences and instructions Claude was working with |
| Handoff brief | Written by Claude at export time: goal, decisions, current state, open questions, the next step |
| Checksums | A SHA-256 hash for every file, so the import can prove nothing is missing or damaged |

## Install

**Claude chat and Cowork (claude.ai or the Claude desktop app)**
1. Download [session-transfer-plugin.zip](https://github.com/tcptyler/Claude-AIO-Importer-and-Exporter/raw/main/release/session-transfer-plugin.zip).
2. Go to Customize > Plugins > Add > Upload plugin, and choose the zip.
3. Make sure code execution and file creation is turned on in Settings.

Skills only, if plugins aren't available to you: upload [export-session.zip](https://github.com/tcptyler/Claude-AIO-Importer-and-Exporter/raw/main/release/export-session.zip) and [import-session.zip](https://github.com/tcptyler/Claude-AIO-Importer-and-Exporter/raw/main/release/import-session.zip) in Customize > Skills.

**Claude Code**

```
/plugin marketplace add tcptyler/Claude-AIO-Importer-and-Exporter
```

```
/plugin install session-transfer@aio-importer-exporter
```

**Export bookmark (for claude.ai chats)**
1. Download [install-bookmarklet.html](https://github.com/tcptyler/Claude-AIO-Importer-and-Exporter/raw/main/release/install-bookmarklet.html) and open it in Chrome, Edge, Brave or Firefox.
2. Show the bookmarks bar (Ctrl+Shift+B, or Cmd+Shift+B on a Mac) and drag the **Export Claude Session** button onto it.

## Export

**A claude.ai chat**
1. In the chat, say **export this session** (or type `/export-session`). Claude writes the handoff brief into the chat's files.
2. Click the **Export Claude Session** bookmark while the chat is open in your browser. A progress box appears in the top right and the `.session.zip` downloads.

If you use the Claude desktop or mobile app, open the same chat in a desktop browser (`https://claude.ai/chat/...`) and click the bookmark there. In Cowork or Claude Code with Claude in Chrome connected, Claude can run the capture for you.

**A Cowork task or Claude Code session:** say **export this session**. Claude writes the brief and saves the zip itself: in Cowork to the task's outputs, in Claude Code to your working folder or a folder you name.

## Import

Start a new chat or Cowork task (or Claude Code session) with the plugin installed, attach the zip, and say **import this session**. Claude:

1. checks every file against its checksum and tells you about anything missing
2. restores artifacts and files (on claude.ai they become downloadable again)
3. reads the handoff brief, the memory notes and the full transcript, and views the images
4. offers to save key facts to your Claude memory, and only does it if you say yes
5. recaps what the session was about, where it stopped, and the next step

Import also accepts:
- the claude.ai JSON files most Chrome exporter extensions save
- the official claude.ai data export (Settings > Privacy > Export data); you pick which chat to load
- Claude Code and Cowork `.jsonl` transcripts
- plain markdown or text transcripts

## Long conversations

Claude reads the transcript in parts. Models with large context windows read all of it. Smaller ones read the brief, the start and the most recent parts in full, and search the rest when a topic comes up. The restore plan shows exactly what was read.

## Privacy and safety

- The bookmark runs only in your claude.ai tab, using your existing sign-in. It reads the same data the claude.ai page itself loads.
- The zip contains the whole conversation and your memory notes. Treat it like the chat itself and keep it private.
- Passwords, API keys and tokens are replaced with `[redacted]` in the handoff brief. The raw transcript is a faithful copy, so anything you pasted into the chat is in it.
- On import, Claude treats the old transcript as a record. It won't repeat actions from it (sending, deleting, buying, running commands) unless you ask again in the new chat.

## Limits

- The bookmark uses claude.ai's internal web API, the same one the site uses. It is not a public API, so a claude.ai update can break the bookmark until this project is updated.
- Pasted images are saved from claude.ai's preview copies, which may be smaller than your originals. Images that are also stored in the chat's files are saved at full size.
- The bookmark needs a desktop browser.
- Cowork tasks whose transcript isn't readable from inside the task fall back to the task's own **Download task data** option plus Claude's brief.

## Troubleshooting

| Problem | Fix |
|---|---|
| Clicking the bookmark does nothing | Open a chat first: the address must look like `claude.ai/chat/...` |
| "Expected JSON ... are you signed in?" | Sign in to claude.ai in that browser and reload the chat |
| "This chat was not found in any of your organizations" | You're signed in to a different account than the one that owns the chat |
| The box lists notes about missing images or files | Those items couldn't be downloaded. Everything else is in the zip, and the import reports what's missing |
| "No handoff brief found" | Say **export this session** in the chat first, then click the bookmark again |

## Repository layout

| Path | What |
|---|---|
| `plugins/session-transfer/` | The plugin: both skills, their scripts, and the bookmark installer |
| `release/` | Ready-to-install zips and the bookmark installer |
| `src/` | Source for the scripts (copied into the skills by `build.py`) |
| `docs/bundle-format.md` | The `.session.zip` format |
| `docs/development.md` | Building and testing |
| `tests/` | Mock claude.ai server and end-to-end tests |
