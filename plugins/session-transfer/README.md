# Claude AIO Importer and Exporter

Take a Claude conversation with you. `/export-session` packs a claude.ai chat, Cowork task or Claude Code session into one `.session.zip`. In a fresh chat or task, attach the zip and say **import this session**: Claude verifies it, restores the files, reads everything and picks up where you left off.

- **export-session:** writes a handoff brief, then captures the full transcript, every pasted image, attachments, every artifact version, workspace files, project knowledge and memory.
- **import-session:** verifies checksums, restores files and artifacts, reads the brief, transcript and images, offers to save key facts to memory, and recaps where you left off.

For claude.ai chats, the capture runs from a one-click bookmark in your browser. Install it from `skills/export-session/assets/install-bookmarklet.html`.

Full documentation: https://github.com/tcptyler/Claude-AIO-Importer-and-Exporter
