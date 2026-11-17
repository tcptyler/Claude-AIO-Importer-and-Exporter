"""Mock of the claude.ai endpoints the capture script uses. Test-only."""
import json, sys, struct, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BAD, GOOD = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
CID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ROOT = "00000000-0000-4000-8000-000000000000"

def png(w, h, rgb=(200, 80, 40)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

LONG = "# Report\n\n" + ("All systems nominal. " * 30)
def msg(uuid, parent, sender, content, idx, **kw):
    d = {"uuid": uuid, "parent_message_uuid": parent, "sender": sender, "index": idx,
         "created_at": f"2026-11-10T14:0{idx}:00Z", "content": content, "files": [], "files_v2": [], "attachments": []}
    d.update(kw); return d

CONV = {
  "uuid": CID, "name": "Logo & launch plan", "model": "claude-opus-5-5", "created_at": "2026-11-10T14:00:00Z",
  "updated_at": "2026-11-10T14:09:00Z", "project_uuid": "p1", "current_leaf_message_uuid": "m6",
  "chat_messages": [
    msg("m1", ROOT, "human", [{"type": "text", "text": "Here is my logo. Make a plan."}], 0,
        files_v2=[{"file_kind": "image", "file_uuid": "f1", "file_name": "logo.png",
                   "preview_url": f"/api/{GOOD}/files/f1/preview", "thumbnail_url": f"/api/{GOOD}/files/f1/thumbnail",
                   "preview_asset": {"url": f"/api/{GOOD}/files/f1/preview", "image_width": 40, "image_height": 30}}],
        attachments=[{"file_name": "notes.txt", "file_type": "text/plain", "extracted_content": "Meeting notes: launch Dec 1."}]),
    msg("m2", "m1", "assistant", [{"type": "thinking", "thinking": "secret reasoning"}, {"type": "text", "text": "Here's the plan."},
        {"type": "tool_use", "name": "artifacts", "input": {"command": "create", "id": "plan", "type": "text/markdown", "title": "Launch Plan", "content": "# Plan\n\nStep 1"}}], 1),
    msg("m3", "m2", "human", [{"type": "text", "text": "ABANDONED BRANCH QUESTION"}], 2),
    msg("m3b", "m2", "human", [{"type": "text", "text": "Mark step 1 done. PDF attached."}], 3,
        files=[{"file_kind": "document", "file_uuid": "doc1", "file_name": "brief.pdf", "document_asset": {"url": f"/api/{GOOD}/files/doc1/document", "page_count": 1}}]),
    msg("m4", "m3b", "assistant", [
        {"type": "tool_use", "name": "artifacts", "input": {"command": "update", "id": "plan", "old_str": "Step 1", "new_str": "Step 1 done ($& kept)\n\nStep 2"}},
        {"type": "tool_use", "name": "web_search", "input": {"query": "launch checklist"}},
        {"type": "tool_result", "content": [{"type": "text", "text": "10 results"}]},
        {"type": "tool_use", "name": "create_file", "input": {"path": "/mnt/user-data/outputs/report.md", "file_text": LONG}},
        {"type": "text", "text": "Updated and wrote report.md."}], 4),
    msg("m5", "m4", "human", [{"type": "text", "text": "Here's the diagram."}], 5,
        files_v2=[{"file_kind": "image", "file_uuid": "f2", "file_name": "diagram.png", "preview_url": f"/api/{GOOD}/files/f2/preview"}]),
    msg("m6", "m5", "assistant", [{"type": "tool_use", "name": "artifacts", "input": {"command": "rewrite", "id": "plan", "content": "# Plan v3\n\nAll done."}},
        {"type": "text", "text": "Done."}], 6),
  ]}

WIGGLE = {"/mnt/user-data/uploads/diagram.png": png(64, 48, (10, 120, 200)),
          "/mnt/user-data/outputs/report.md": LONG.encode(),
          "/mnt/user-data/outputs/session-export/HANDOFF.md": b"# Handoff: Logo & launch plan\n\nNext step: ship.",
          "/mnt/user-data/outputs/session-export/MEMORY.md": b"# Memory\n\nUser prefers concise answers.",
          "/mnt/user-data/outputs/old-chat-20261101-0900.session.zip": b"PK old"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path); p = u.path; q = parse_qs(u.query)
        if p.startswith("/chat/"): return self.send(200, b"<!doctype html><html><body><h1>chat</h1></body></html>", "text/html")
        if p == "/api/organizations": return self.send(200, [{"uuid": BAD}, {"uuid": GOOD}])
        if p == f"/api/organizations/{BAD}/chat_conversations/{CID}": return self.send(404, {"error": "not found"})
        if p == f"/api/organizations/{GOOD}/chat_conversations/{CID}":
            assert q.get("tree") == ["True"] and q.get("render_all_tools") == ["true"]
            return self.send(200, CONV)
        if p == f"/api/organizations/{GOOD}/conversations/{CID}/wiggle/list-files": return self.send(200, {"files": list(WIGGLE)})
        if p == f"/api/organizations/{GOOD}/conversations/{CID}/wiggle/download-file":
            return self.send(200, WIGGLE[q["path"][0]], "application/octet-stream")
        if p == f"/api/{GOOD}/files/f1/preview": return self.send(200, png(40, 30), "image/png")
        if p == f"/api/{GOOD}/files/f2/preview": return self.send(500, {"error": "should use workspace original"})
        if p == f"/api/{GOOD}/files/doc1/document": return self.send(200, b"%PDF-1.4 fake pdf", "application/pdf")
        if p == f"/api/organizations/{GOOD}/projects/p1": return self.send(200, {"uuid": "p1", "name": "Launch", "prompt_template": "Always cite sources."})
        if p == f"/api/organizations/{GOOD}/projects/p1/docs": return self.send(200, [{"file_name": "brand.md", "content": "# Brand\nOrange."}])
        return self.send(404, {"error": p})

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
