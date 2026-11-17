# Development

## Layout

- `src/sessionkit.py`: shared library (bundle writer, manifest, transcript format, normalizers for claude.ai JSON and Claude Code / Cowork JSONL, chunking, index). Used by both skills.
- `src/capture.js`: the browser capture for claude.ai (bookmark, console, or Claude in Chrome).
- `src/export_local.py`: export for Claude Code and Cowork sessions, plus the claude.ai sandbox fallback.
- `src/import_bundle.py`: verify, unpack, convert, chunk, and write the restore plan.
- `plugins/session-transfer/`: the plugin. `skills/*/SKILL.md` and `references/handoff-template.md` are edited here. `skills/*/scripts/`, `skills/*/references/bundle-format.md` and `skills/export-session/assets/` are generated: edit `src/` or `docs/` and rebuild.

## Build

```bash
python3 build.py
```

This copies the sources into the skills, injects the bundle README into `capture.js`, builds the bookmark installer page, and writes `release/`. Commit the regenerated files: Claude Code installs the plugin straight from `plugins/session-transfer/`.

## Test

```bash
python3 tests/test_all.py
```

Standard library only, plus Node.js and Playwright (with a Chromium browser) for the browser tests. Without Playwright those tests are skipped.

What it covers:
- the built bookmark, clicked in headless Chromium against `tests/mock_claude.py` (a mock of the claude.ai endpoints the capture uses), then imported and checked: branch selection, images from previews and from the workspace, documents, pasted text, artifact versions (including `$&` in an edit), workspace files, the brief, project knowledge, checksums, and the publish folder
- the raw `capture.js` run the way Claude in Chrome runs it
- import of a bare claude.ai JSON, of the official multi-chat export (with and without `--pick`), and of a Claude Code JSONL with pasted images, screenshots, a compaction summary, system reminders and subagent messages
- the local exporter end to end
- refusal of zips with paths that escape the restore folder
- chunking and PARTIAL mode on a large transcript
- that the committed generated files match a fresh build

## Notes on the claude.ai internal API

The capture uses the endpoints the claude.ai web app calls. They are undocumented and can change:

- `GET /api/organizations` (fallback when the `lastActiveOrg` cookie doesn't own the chat)
- `GET /api/organizations/{org}/chat_conversations/{id}?tree=True&rendering_mode=messages&render_all_tools=true`
- `GET /api/organizations/{org}/conversations/{id}/wiggle/list-files` and `.../wiggle/download-file?path=...`
- image `preview_url` / `preview_asset.url` (fallback `thumbnail_url`) and document `document_asset.url` on each message's `files` / `files_v2`
- `GET /api/organizations/{org}/projects/{project}` and `.../docs` (best effort)

If an export starts failing, compare a fresh response from these endpoints with `tests/mock_claude.py` and update both.
