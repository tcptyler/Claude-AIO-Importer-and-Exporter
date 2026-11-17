"""sessionkit: shared library for the session-transfer plugin.

Builds and reads "claude-session-bundle" zips. Standard library only, so it
runs in the claude.ai / Cowork sandbox, in Claude Code, and on any machine
with Python 3.8+.

Pieces:
  * BundleWriter        collect files, write manifest.json with sha256, zip
  * Transcript model    a list of messages, each a list of typed blocks
  * render_markdown     the one transcript format every source is turned into
  * normalize_claudeai  claude.ai internal API JSON  -> transcript model
  * normalize_jsonl     Claude Code / Cowork JSONL   -> transcript model
  * split_parts         cut a transcript into readable parts by message
  * build_index         a one-line-per-message table of contents
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import struct
import zipfile
from collections import Counter, OrderedDict

FORMAT = "claude-session-bundle"
FORMAT_VERSION = 1
TOOL_VERSION = "1.0.0"
HEADER_RE = re.compile(r"^### \[(\d{4,})\] (.+?) · (.*)$")
IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PATH_REF_RE = re.compile(r"\(((?:\.\./)*(?:artifacts|attachments|files|images|project)/[^)]+)\)")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.S)
CLAUDEAI_ROOT_PARENT = "00000000-0000-4000-8000-000000000000"

# ----------------------------------------------------------------- small utils


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fmt_time(ts) -> str:
    """ISO timestamp -> 'YYYY-MM-DD HH:MM UTC' (best effort, never raises)."""
    if not ts:
        return "time unknown"
    try:
        s = str(ts).replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)[:19]


def slug(text, maxlen=60, default="item") -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-._").lower()
    return (s[:maxlen].rstrip("-._") or default)


def safe_name(name, default="file") -> str:
    """Keep a readable file name but drop path parts and characters that break zips."""
    base = str(name or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]+", "_", base).strip(" .")
    return base[:120] or default


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_ext(data: bytes, fallback="bin") -> str:
    head = data[:16]
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.lstrip().startswith(b"<svg") or b"<svg" in data[:200]:
        return "svg"
    return fallback


def image_size(data: bytes):
    """Return (width, height) for PNG/JPEG/GIF/WEBP, else None."""
    try:
        if data.startswith(b"\x89PNG"):
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                w = 1 + int.from_bytes(data[24:27], "little")
                h = 1 + int.from_bytes(data[27:30], "little")
                return (w, h)
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return (w & 0x3FFF, h & 0x3FFF)
            if chunk == b"VP8L":
                b = data[21:25]
                w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                return (w, h)
        if data.startswith(b"\xff\xd8"):
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return (w, h)
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
    except Exception:
        return None
    return None


def est_text_tokens(text: str) -> int:
    return int(math.ceil(len(text or "") / 3.6))


def est_image_tokens(size) -> int:
    """Rough vision cost. Images are scaled to fit ~1568px on the long edge."""
    if not size:
        return 1600
    w, h = size
    if not w or not h:
        return 1600
    scale = min(1.0, 1568.0 / max(w, h))
    w, h = w * scale, h * scale
    return int(max(85, min(1600, (w * h) / 750)))


def one_line(text, limit=240) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


def strip_reminders(text: str) -> str:
    return REMINDER_RE.sub("", text or "")


ARTIFACT_EXT = {
    "text/html": "html",
    "text/markdown": "md",
    "image/svg+xml": "svg",
    "application/vnd.ant.mermaid": "mmd",
    "application/vnd.ant.react": "jsx",
    "text/plain": "txt",
}
LANG_EXT = {
    "python": "py", "javascript": "js", "typescript": "ts", "jsx": "jsx", "tsx": "tsx",
    "html": "html", "css": "css", "json": "json", "bash": "sh", "shell": "sh", "sh": "sh",
    "sql": "sql", "yaml": "yaml", "yml": "yaml", "markdown": "md", "java": "java", "go": "go",
    "rust": "rs", "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "c#": "cs", "ruby": "rb",
    "php": "php", "swift": "swift", "kotlin": "kt", "powershell": "ps1", "xml": "xml", "toml": "toml",
}


def artifact_ext(atype, language) -> str:
    if atype in ARTIFACT_EXT:
        return ARTIFACT_EXT[atype]
    if language and str(language).lower() in LANG_EXT:
        return LANG_EXT[str(language).lower()]
    return "txt"


# ------------------------------------------------------------- bundle writer


class BundleWriter:
    """Collect files in memory, then write a zip with manifest.json."""

    def __init__(self):
        self.files: "OrderedDict[str, tuple]" = OrderedDict()
        self.warnings: list = []

    def unique(self, path: str) -> str:
        path = path.replace("\\", "/").lstrip("/")
        parts = [p for p in path.split("/") if p not in ("", ".", "..")]
        path = "/".join(parts) or "file"
        if path not in self.files:
            return path
        stem, dot, ext = path.rpartition(".")
        if not dot or "/" in ext:
            stem, ext = path, ""
        i = 2
        while True:
            cand = f"{stem}-{i}.{ext}" if ext else f"{stem}-{i}"
            if cand not in self.files:
                return cand
            i += 1

    def add(self, path: str, data, role: str, **meta) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        path = self.unique(path)
        self.files[path] = (bytes(data), role, {k: v for k, v in meta.items() if v not in (None, "", [])})
        return path

    def has(self, path) -> bool:
        return path in self.files

    def manifest(self, source: dict, counts: dict, extra: dict | None = None) -> dict:
        entries = []
        for path, (data, role, meta) in self.files.items():
            e = {"path": path, "bytes": len(data), "sha256": sha256(data), "role": role}
            e.update(meta)
            entries.append(e)
        m = {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "created_by": f"session-transfer {TOOL_VERSION}",
            "exported_at": now_iso(),
            "source": source,
            "counts": counts,
            "warnings": self.warnings,
            "files": entries,
        }
        if extra:
            m.update(extra)
        return m

    def write_zip(self, out_path: str, manifest: dict) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for path, (data, _role, _meta) in self.files.items():
                ext = path.rsplit(".", 1)[-1].lower()
                method = zipfile.ZIP_STORED if ext in ("png", "jpg", "jpeg", "gif", "webp", "zip", "pdf") else zipfile.ZIP_DEFLATED
                z.writestr(zipfile.ZipInfo(path, date_time=_dt.datetime.now().timetuple()[:6]), data, compress_type=method)
        return out_path


# ---------------------------------------------------------- transcript model
#
# message = {"n": int, "role": "user"|"assistant"|"system", "label": str,
#            "time": iso|None, "blocks": [block, ...], "id": str|None}
# block types:
#   {"type":"text","text":...}
#   {"type":"thinking","text":...}
#   {"type":"image","path":..., "name":..., "note":...}        path is bundle-relative
#   {"type":"file","path":..., "name":..., "note":...}         attachment / upload
#   {"type":"artifact","title":..., "path":..., "command":..., "version":int}
#   {"type":"tool","name":..., "summary":...}
#   {"type":"result","summary":..., "error":bool}
#   {"type":"event","text":...}                                 compaction summary, notices

ROLE_LABEL = {"user": "User", "assistant": "Claude", "system": "System"}


def _rel(path: str) -> str:
    return "../" + path if path and not path.startswith("../") else path


def render_message(m: dict, include_thinking=False) -> str:
    label = m.get("label") or ROLE_LABEL.get(m["role"], m["role"].title())
    out = [f"### [{m['n']:04d}] {label} · {fmt_time(m.get('time'))}", ""]
    for b in m["blocks"]:
        t = b["type"]
        if t == "text":
            out += [b["text"].rstrip(), ""]
        elif t == "thinking":
            if include_thinking and b.get("text", "").strip():
                out += ["> Claude's reasoning:", "> " + one_line(b["text"], 2000), ""]
        elif t == "image":
            note = f" ({b['note']})" if b.get("note") else ""
            if b.get("path"):
                out += [f"![{b.get('name') or 'image'}]({_rel(b['path'])}){note}", ""]
            else:
                out += [f"> Image: {b.get('name') or 'image'} (not captured){note}", ""]
        elif t == "file":
            note = f" ({b['note']})" if b.get("note") else ""
            if b.get("path"):
                out += [f"> Attachment: [{b.get('name') or 'file'}]({_rel(b['path'])}){note}", ""]
            else:
                out += [f"> Attachment: {b.get('name') or 'file'} (not captured){note}", ""]
        elif t == "artifact":
            where = f" -> [{b['path']}]({_rel(b['path'])})" if b.get("path") else ""
            ver = f" v{b['version']}" if b.get("version") else ""
            out += [f"> Artifact {b.get('command') or 'create'}{ver}: \"{b.get('title') or 'untitled'}\"{where}", ""]
        elif t == "tool":
            out += [f"> Tool · {b.get('name')}: {b.get('summary') or ''}".rstrip(), ""]
        elif t == "result":
            tag = "Error" if b.get("error") else "Result"
            if b.get("summary"):
                out += [f"> {tag}: {b['summary']}", ""]
        elif t == "event":
            out += [b["text"].rstrip(), ""]
    return "\n".join(out).rstrip() + "\n"


def render_markdown(meta: dict, messages: list, include_thinking=False) -> str:
    fm = ["---"]
    for k in ("title", "source", "conversation_id", "model", "created_at", "updated_at", "url", "exported_at"):
        if meta.get(k):
            fm.append(f"{k}: {json.dumps(str(meta[k]), ensure_ascii=False)}")
    fm.append(f"messages: {len(messages)}")
    fm.append("---")
    head = "\n".join(fm) + f"\n\n# {meta.get('title') or 'Claude session'}\n\n"
    head += ("Full transcript of the current branch. Images, attachments and artifacts are "
             "linked by relative path inside this bundle.\n\n")
    return head + "\n".join(render_message(m, include_thinking) for m in messages)


# ------------------------------------------------------------ chunk / index


def split_messages(markdown: str):
    """Split a rendered transcript into (preamble, [(n, label, time, text)])."""
    lines = markdown.splitlines(keepends=True)
    pre, msgs, cur = [], [], None
    for ln in lines:
        mm = HEADER_RE.match(ln.rstrip("\n"))
        if mm:
            if cur:
                msgs.append(cur)
            cur = [int(mm.group(1)), mm.group(2), mm.group(3), [ln]]
        elif cur:
            cur[3].append(ln)
        else:
            pre.append(ln)
    if cur:
        msgs.append(cur)
    return "".join(pre), [(n, lab, tm, "".join(body)) for n, lab, tm, body in msgs]


def split_parts(markdown: str, max_tokens=18000):
    """Return list of part texts, each under ~max_tokens, cut on message boundaries."""
    pre, msgs = split_messages(markdown)
    if not msgs:  # foreign transcript without our headers: cut on blank lines
        paras = re.split(r"(\n\s*\n)", markdown)
        msgs = []
        buf = ""
        for p in paras:
            buf += p
            if est_text_tokens(buf) > max_tokens // 2:
                msgs.append((len(msgs) + 1, "Text", "", buf))
                buf = ""
        if buf.strip():
            msgs.append((len(msgs) + 1, "Text", "", buf))
        pre = ""
    parts, cur, cur_tok = [], [], est_text_tokens(pre)
    first = True
    for n, lab, tm, text in msgs:
        t = est_text_tokens(text)
        if t > max_tokens:  # one giant message: hard-split it
            if cur:
                parts.append((first, cur))
                first = False
                cur, cur_tok = [], 0
            step = int(max_tokens * 3.6)
            for i in range(0, len(text), step):
                chunk = text[i:i + step]
                if i:
                    chunk = f"### [{n:04d}] {lab} · {tm} (continued)\n\n" + chunk
                parts.append((first, [chunk]))
                first = False
            continue
        if cur and cur_tok + t > max_tokens:
            parts.append((first, cur))
            first = False
            cur, cur_tok = [], 0
        cur.append(text)
        cur_tok += t
    if cur:
        parts.append((first, cur))
    out = []
    for is_first, texts in parts:
        body = "".join(texts)
        out.append((pre + body) if is_first and pre else body)
    return out or [markdown]


def message_refs(text: str):
    strip = lambda p: re.sub(r"^(\.\./)+", "", p)
    imgs = [strip(p) for p in IMG_REF_RE.findall(text)]
    other = [strip(p) for p in PATH_REF_RE.findall(text) if strip(p) not in imgs]
    return imgs, other


def first_text_line(text: str) -> str:
    fallback = ""
    for ln in text.splitlines()[1:]:
        s = ln.strip()
        if not s or s.startswith("![") or s.startswith("> Image"):
            continue
        if s.startswith(">"):
            fallback = fallback or s
            continue
        return one_line(re.sub(r"[*_`#>]+", "", s).strip(" -"), 110)
    return one_line(fallback.lstrip("> "), 110)


def build_index(markdown: str, part_names: list, parts: list) -> str:
    _pre, msgs = split_messages(markdown)
    where = {}
    for name, text in zip(part_names, parts):
        for _p, pm in [split_messages(text)]:
            for n, *_ in pm:
                where.setdefault(n, name)
    rows = ["# Transcript index", "",
            "One line per message. Use it to jump to the right part, or grep the parts for details.", "",
            "| # | Who | When | Part | Starts with | Images | Files |", "|---|---|---|---|---|---|---|"]
    for n, lab, tm, text in msgs:
        imgs, other = message_refs(text)
        starts = first_text_line(text).replace("|", "/")
        rows.append(f"| {n} | {lab} | {tm} | {where.get(n, '')} | {starts} | {len(imgs) or ''} | {len(other) or ''} |")
    return "\n".join(rows) + "\n"


# ------------------------------------------------------- claude.ai normalizer


def claudeai_branch(conv: dict) -> list:
    msgs = conv.get("chat_messages") or []
    by_id = {m.get("uuid"): m for m in msgs if m.get("uuid")}
    leaf = conv.get("current_leaf_message_uuid")
    path, seen = [], set()
    while leaf and leaf in by_id and leaf not in seen:
        seen.add(leaf)
        path.append(by_id[leaf])
        leaf = by_id[leaf].get("parent_message_uuid")
    if path and (not leaf or leaf == CLAUDEAI_ROOT_PARENT or leaf not in by_id):
        return list(reversed(path))
    return sorted(msgs, key=lambda m: (m.get("index") or 0, m.get("created_at") or ""))


def _tool_summary(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return one_line(inp, 200)
    for key in ("description", "query", "command", "file_path", "path", "url", "prompt", "pattern", "title", "skill"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return one_line(v, 200)
    small = {k: v for k, v in inp.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) < 120}
    return one_line(json.dumps(small, ensure_ascii=False), 200) if small else ""


def _result_summary(content) -> tuple:
    """tool_result content -> (summary text, [image blocks as (media_type, b64)])"""
    images = []
    if isinstance(content, str):
        return one_line(content, 300), images
    texts = []
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                texts.append(c.get("text") or "")
            elif c.get("type") == "image":
                src = c.get("source") or {}
                if src.get("type") == "base64" and src.get("data"):
                    images.append((src.get("media_type"), src["data"]))
    return one_line(" ".join(texts), 300), images


CONTENT_KEYS = ("content", "file_text", "widget_code", "code", "html")


def normalize_claudeai(conv: dict, bw: BundleWriter | None = None, file_map: dict | None = None):
    """claude.ai conversation JSON -> (meta, messages).

    If `bw` is given, artifacts and created files are written into it (used
    when importing a bare conversation JSON that did not come with files).
    `file_map` maps file uuids / names to bundle paths when a capture already
    stored the binaries.
    """
    file_map = file_map or {}
    meta = {
        "title": conv.get("name") or "Untitled chat",
        "source": "claude.ai",
        "conversation_id": conv.get("uuid"),
        "model": conv.get("model"),
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "url": f"https://claude.ai/chat/{conv['uuid']}" if conv.get("uuid") else None,
    }
    artifacts = {}  # id -> {"title", "type", "language", "content", "versions": [paths]}
    out = []
    for i, m in enumerate(claudeai_branch(conv), 1):
        role = "user" if m.get("sender") == "human" else "assistant"
        blocks = []
        for f in (m.get("files_v2") or m.get("files") or []):
            name = f.get("file_name") or "file"
            path = file_map.get(f.get("file_uuid")) or file_map.get(name)
            kind = "image" if (f.get("file_kind") == "image") else "file"
            blocks.append({"type": kind, "name": name, "path": path})
        for a in (m.get("attachments") or []):
            name = a.get("file_name") or "pasted-text.txt"
            path = file_map.get(a.get("id") or "") or file_map.get(f"att:{m.get('uuid')}:{name}")
            text = a.get("extracted_content") or ""
            if not path and bw is not None and text:
                path = bw.add(f"attachments/m{i:04d}-{safe_name(name)}" + ("" if name.lower().endswith((".txt", ".md")) else ".txt"),
                              text, "attachment", message=i, original_name=name)
            blocks.append({"type": "file", "name": name, "path": path, "note": f"{len(text)} chars of extracted text" if text else None})
        content = m.get("content")
        if not content and m.get("text"):
            content = [{"type": "text", "text": m["text"]}]
        for c in content or []:
            t = c.get("type")
            if t == "text" and (c.get("text") or "").strip():
                blocks.append({"type": "text", "text": c["text"]})
            elif t == "thinking":
                blocks.append({"type": "thinking", "text": c.get("thinking") or c.get("text") or ""})
            elif t == "tool_use":
                name = c.get("name") or "tool"
                inp = c.get("input") or {}
                if name == "artifacts" and isinstance(inp, dict):
                    aid = inp.get("id") or f"artifact-{len(artifacts) + 1}"
                    a = artifacts.setdefault(aid, {"title": inp.get("title") or aid, "type": inp.get("type"),
                                                   "language": inp.get("language"), "content": "", "versions": []})
                    cmd = inp.get("command") or "create"
                    if inp.get("title"):
                        a["title"] = inp["title"]
                    if inp.get("type"):
                        a["type"] = inp["type"]
                    if cmd == "update" and isinstance(inp.get("old_str"), str):
                        a["content"] = a["content"].replace(inp["old_str"], inp.get("new_str") or "", 1)
                    elif isinstance(inp.get("content"), str):
                        a["content"] = inp["content"]
                    v = len(a["versions"]) + 1
                    path = None
                    if bw is not None:
                        ext = artifact_ext(a["type"], a.get("language"))
                        path = bw.add(f"artifacts/{slug(a['title'])}/v{v:03d}.{ext}", a["content"], "artifact-version",
                                      artifact_id=aid, title=a["title"], version=v)
                    a["versions"].append(path)
                    blocks.append({"type": "artifact", "title": a["title"], "command": cmd, "version": v, "path": path})
                elif isinstance(inp, dict) and any(isinstance(inp.get(k), str) and len(inp.get(k)) > 200 for k in CONTENT_KEYS):
                    key = next(k for k in CONTENT_KEYS if isinstance(inp.get(k), str) and len(inp.get(k)) > 200)
                    fname = safe_name(inp.get("path") or inp.get("file_path") or inp.get("title") or f"{name}.txt")
                    path = file_map.get(fname)
                    if not path and bw is not None:
                        path = bw.add(f"artifacts/tool-{slug(name)}/m{i:04d}-{fname}", inp[key], "tool-content", tool=name, message=i)
                    blocks.append({"type": "artifact", "title": fname, "command": name, "path": path})
                else:
                    blocks.append({"type": "tool", "name": name, "summary": _tool_summary(name, inp)})
            elif t == "tool_result":
                summ, _imgs = _result_summary(c.get("content"))
                blocks.append({"type": "result", "summary": summ, "error": bool(c.get("is_error"))})
        out.append({"n": i, "role": role, "time": m.get("created_at"), "blocks": blocks, "id": m.get("uuid")})
    if bw is not None:
        for aid, a in artifacts.items():
            if a["versions"]:
                ext = artifact_ext(a["type"], a.get("language"))
                bw.add(f"artifacts/{slug(a['title'])}/latest.{ext}", a["content"], "artifact-latest",
                       artifact_id=aid, title=a["title"], versions=len(a["versions"]))
    return meta, out


# ------------------------------------------- Claude Code / Cowork normalizer

FILE_TOOLS_RE = re.compile(r"(^|_|\b)(write|edit|multiedit|notebookedit|create_file|str_replace|write_file|edit_file|edit_block)$", re.I)
SYSTEM_PREFIXES = ("<task-notification>", "<command-name>", "<command-message>", "<local-command-stdout>",
                   "Another Claude session sent a message", "[SYSTEM NOTIFICATION")


def read_jsonl(path_or_bytes) -> list:
    data = path_or_bytes
    if isinstance(path_or_bytes, str):
        with open(path_or_bytes, "rb") as fh:
            data = fh.read()
    rows = []
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def looks_like_jsonl_transcript(rows) -> bool:
    return any(isinstance(r, dict) and r.get("type") in ("user", "assistant") and isinstance(r.get("message"), dict) for r in rows[:400])


def normalize_jsonl(rows: list, bw: BundleWriter | None = None, include_tool_images=True):
    """Claude Code / Cowork JSONL rows -> (meta, messages, touched_files).

    Images (pasted or tool screenshots) are written into `bw` when given.
    A "turn" groups a user prompt and Claude's whole reply, including tool
    calls and results, so the transcript reads like the chat did.
    """
    seen, entries = set(), []
    for r in rows:
        if not isinstance(r, dict) or r.get("type") not in ("user", "assistant") or r.get("isSidechain"):
            continue
        if not isinstance(r.get("message"), dict):
            continue
        u = r.get("uuid")
        if u and u in seen:
            continue
        seen.add(u)
        entries.append(r)

    models = Counter()
    touched = OrderedDict()
    out = []
    cur = None
    img_count = 0

    def new_msg(role, ts, label=None):
        m = {"n": len(out) + 1, "role": role, "time": ts, "blocks": [], "label": label}
        out.append(m)
        return m

    def save_image(media_type, b64, n, note):
        nonlocal img_count
        if bw is None:
            return None
        import base64
        try:
            data = base64.b64decode(b64)
        except Exception:
            return None
        img_count += 1
        ext = sniff_ext(data, (media_type or "image/png").split("/")[-1])
        return bw.add(f"images/m{n:04d}-{img_count:03d}.{ext}", data, "image", message=n, note=note,
                      width=(image_size(data) or (None, None))[0], height=(image_size(data) or (None, None))[1])

    for r in entries:
        msg = r["message"]
        ts = r.get("timestamp")
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        content = [c for c in (content or []) if isinstance(c, dict)]
        if r["type"] == "assistant":
            if msg.get("model") and not str(msg.get("model")).startswith("<"):
                models[msg["model"]] += 1
            if cur is None or cur["role"] != "assistant":
                cur = new_msg("assistant", ts)
            for c in content:
                t = c.get("type")
                if t == "text" and (c.get("text") or "").strip():
                    cur["blocks"].append({"type": "text", "text": c["text"]})
                elif t == "thinking":
                    cur["blocks"].append({"type": "thinking", "text": c.get("thinking") or ""})
                elif t == "tool_use":
                    name = c.get("name") or "tool"
                    inp = c.get("input") or {}
                    cur["blocks"].append({"type": "tool", "name": name, "summary": _tool_summary(name, inp)})
                    if isinstance(inp, dict) and FILE_TOOLS_RE.search(name.split("__")[-1]):
                        fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                        if isinstance(fp, str) and fp:
                            touched[fp] = name
            continue

        # user-side entries
        if r.get("isMeta"):
            continue
        results = [c for c in content if c.get("type") == "tool_result"]
        others = [c for c in content if c.get("type") != "tool_result"]
        if results and cur is not None and cur["role"] == "assistant":
            for c in results:
                summ, imgs = _result_summary(c.get("content"))
                cur["blocks"].append({"type": "result", "summary": summ, "error": bool(c.get("is_error"))})
                if include_tool_images:
                    for mt, b64 in imgs:
                        p = save_image(mt, b64, cur["n"], "tool screenshot")
                        if p:
                            cur["blocks"].append({"type": "image", "path": p, "name": os.path.basename(p), "note": "tool screenshot"})
        if not others:
            continue
        texts = [strip_reminders(c.get("text") or "") for c in others if c.get("type") == "text"]
        joined = "\n\n".join(t for t in texts if t.strip()).strip()
        has_image = any(c.get("type") == "image" for c in others)
        if not joined and not has_image:
            continue
        if r.get("isCompactSummary"):
            m = new_msg("system", ts, "Context summary")
            m["blocks"].append({"type": "event", "text": "_Earlier context was auto-summarized here. Summary:_\n\n" + joined})
            cur = m
            continue
        if joined.startswith(SYSTEM_PREFIXES):
            m = new_msg("system", ts, "System event")
            m["blocks"].append({"type": "event", "text": "> " + one_line(joined, 300)})
            cur = m
            continue
        m = new_msg("user", ts)
        if joined:
            m["blocks"].append({"type": "text", "text": joined})
        for c in others:
            if c.get("type") == "image":
                src = c.get("source") or {}
                if src.get("type") == "base64" and src.get("data"):
                    p = save_image(src.get("media_type"), src["data"], m["n"], "pasted image")
                    m["blocks"].append({"type": "image", "path": p, "name": os.path.basename(p) if p else "image"})
                else:
                    m["blocks"].append({"type": "image", "path": None, "name": "image", "note": "stored by reference only"})
            elif c.get("type") == "document":
                m["blocks"].append({"type": "file", "path": None, "name": (c.get("title") or "document"), "note": "inline document"})
        cur = m

    first_user = next((b["text"] for m in out if m["role"] == "user" for b in m["blocks"] if b["type"] == "text"), "")
    sid = next((r.get("sessionId") for r in rows if isinstance(r, dict) and r.get("sessionId")), None)
    cwd = next((r.get("cwd") for r in rows if isinstance(r, dict) and r.get("cwd")), None)
    entry = next((r.get("entrypoint") for r in rows if isinstance(r, dict) and r.get("entrypoint")), "") or ""
    meta = {
        "title": one_line(first_user.splitlines()[0] if first_user else "Claude session", 80),
        "source": "cowork" if "cowork" in entry.lower() or "agent" in entry.lower() else "claude-code",
        "conversation_id": sid,
        "model": models.most_common(1)[0][0] if models else None,
        "created_at": entries[0].get("timestamp") if entries else None,
        "updated_at": entries[-1].get("timestamp") if entries else None,
        "cwd": cwd,
        "entrypoint": entry or None,
    }
    return meta, out, touched


def counts_for(messages: list) -> dict:
    c = Counter()
    for m in messages:
        c["messages"] += 1
        for b in m["blocks"]:
            if b["type"] == "image":
                c["images"] += 1
            elif b["type"] == "file":
                c["attachments"] += 1
            elif b["type"] == "artifact":
                c["artifact_edits"] += 1
            elif b["type"] == "tool":
                c["tool_calls"] += 1
    return dict(c)


BUNDLE_README = """# Claude session bundle

This zip is a complete export of one Claude conversation: {title}

## What's inside

| Folder | Contents |
|---|---|
| `brief/` | Handoff notes written by Claude at export time: goals, decisions, current state, next steps, and the memory/instructions it was using |
| `transcript/transcript.md` | Every message on the current branch, in order, with links to images and files |
| `images/` | Every image pasted or uploaded into the chat, plus screenshots |
| `attachments/` | Uploaded documents and pasted text |
| `artifacts/` | Every artifact, one file per version, plus `latest` |
| `files/` | Files from the chat's workspace (uploads, outputs Claude created, files edited) |
| `memory/`, `project/` | Instruction and memory files, project instructions and knowledge (when available) |
| `raw/` | The original data exactly as captured, for lossless re-processing |
| `manifest.json` | Every file with its size and SHA-256 checksum |

## How to continue this conversation

1. Open a new chat or Cowork task (with the session-transfer plugin installed).
2. Attach this zip and say: **import this session**.
3. Claude verifies the bundle, reads everything, restores the files, and picks up where you left off.

This file is private data. Anyone with the zip can read the whole conversation.
"""
