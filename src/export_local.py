#!/usr/bin/env python3
"""Export a Claude Code or Cowork session (or a claude.ai sandbox fallback) to a
claude-session-bundle zip.

Typical use (run by the export-session skill):

    python3 export_local.py --brief-dir /tmp/session-brief
    python3 export_local.py --list                 # show candidate transcripts
    python3 export_local.py --transcript PATH.jsonl --out ~/Downloads

Finds the current session's transcript automatically (CLAUDE_CODE_SESSION_ID,
then the newest transcript for the working directory). Collects: the full
transcript, every pasted image, files the session created or edited,
CLAUDE.md / auto-memory files, Cowork or sandbox uploads and outputs, the
handoff brief Claude wrote, and the raw JSONL. Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sessionkit as sk  # noqa: E402

MAX_FILE = 25 * 1024 * 1024
MAX_DIR_TOTAL = 300 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache"}


def encode_cwd(path: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in path)


def config_roots() -> list:
    roots = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        roots.append(os.environ["CLAUDE_CONFIG_DIR"])
    roots.append(os.path.expanduser("~/.claude"))
    roots += glob.glob("/sessions/*/mnt/.claude")          # Cowork VM mount
    roots += glob.glob("/home/*/.claude")
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "Library/Application Support/Claude/local-agent-mode-sessions"),
                 os.path.join(os.environ.get("APPDATA", ""), "Claude/local-agent-mode-sessions")):
        if os.path.isdir(base):
            roots += glob.glob(os.path.join(base, "**/.claude"), recursive=True)
    seen, out = set(), []
    for r in roots:
        r = os.path.abspath(r)
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            out.append(r)
    return out


def candidates() -> list:
    found = []
    for root in config_roots():
        for p in glob.glob(os.path.join(root, "projects", "*", "*.jsonl")):
            try:
                found.append((os.path.getmtime(p), p))
            except OSError:
                pass
    found.sort(reverse=True)
    return [p for _, p in found]


def find_transcript(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    cands = candidates()
    if sid:
        for p in cands:
            if os.path.basename(p) == f"{sid}.jsonl":
                return p
    enc = encode_cwd(os.getcwd())
    for p in cands:
        if os.path.basename(os.path.dirname(p)) == enc:
            return p
    return cands[0] if cands else None


def first_prompt(path: str) -> str:
    try:
        rows = sk.read_jsonl(path)
        _m, msgs, _t = sk.normalize_jsonl(rows, None)
        for m in msgs:
            if m["role"] == "user":
                for b in m["blocks"]:
                    if b["type"] == "text":
                        return sk.one_line(b["text"], 90)
    except Exception:
        pass
    return ""


def add_tree(bw: sk.BundleWriter, src: str, dest_prefix: str, role: str, exclude=()) -> int:
    total = n = 0
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            if any(x(full) for x in exclude) or os.path.islink(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > MAX_FILE:
                bw.warnings.append(f"Skipped {full}: {size // (1024 * 1024)} MB is over the 25 MB per-file limit")
                continue
            if total + size > MAX_DIR_TOTAL:
                bw.warnings.append(f"Stopped copying {src}: over 300 MB")
                return n
            rel = os.path.relpath(full, src)
            with open(full, "rb") as fh:
                bw.add(f"{dest_prefix}/{rel}", fh.read(), role, original_path=full)
            total += size
            n += 1
    return n


def is_bundle_artifact(path: str) -> bool:
    base = os.path.basename(path)
    return base.endswith(".session.zip") or "/session-export/" in path.replace("\\", "/")


def collect_memory(bw, cwd, transcript):
    n = 0
    seen = set()
    d = os.path.abspath(cwd or os.getcwd())
    chain = []
    while True:
        chain.append(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    paths = []
    for d in chain:
        for name in ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md")):
            paths.append(os.path.join(d, name))
    paths.append(os.path.expanduser("~/.claude/CLAUDE.md"))
    for p in paths:
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isfile(rp):
            continue
        seen.add(rp)
        with open(rp, "rb") as fh:
            label = sk.slug(os.path.dirname(p).strip("/") or "root", 80)
            bw.add(f"memory/instructions/{label}--{os.path.basename(p)}", fh.read(), "instructions", original_path=p)
        n += 1
    if transcript:
        auto = os.path.join(os.path.dirname(transcript), "memory")
        if os.path.isdir(auto):
            n += add_tree(bw, auto, "memory/auto-memory", "auto-memory")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcript", help="path to a session .jsonl (default: find the current session)")
    ap.add_argument("--list", action="store_true", help="list candidate transcripts and exit")
    ap.add_argument("--detect", action="store_true", help="print whether this is a local session (Claude Code / Cowork) or a claude.ai chat, and exit")
    ap.add_argument("--brief-dir", help="folder with HANDOFF.md / MEMORY.md written by Claude")
    ap.add_argument("--fallback-transcript", help="markdown transcript written from context, used when no .jsonl exists")
    ap.add_argument("--include", action="append", default=[], help="extra file or folder to include (repeatable)")
    ap.add_argument("--out", help="output folder (default: /mnt/user-data/outputs if present, else the working folder)")
    ap.add_argument("--title", help="title for the bundle")
    ap.add_argument("--thinking", action="store_true", help="include Claude's reasoning in transcript.md")
    ap.add_argument("--no-raw", action="store_true", help="leave out raw transcript files")
    ap.add_argument("--no-edited-files", action="store_true", help="leave out files the session created or edited")
    a = ap.parse_args(argv)

    if a.detect:
        t = find_transcript(a.transcript)
        fresh = bool(t) and (time.time() - os.path.getmtime(t) < 600)
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
        if t and (fresh or (sid and os.path.basename(t) == f"{sid}.jsonl")):
            mode = "local"
        elif os.path.isdir("/mnt/user-data"):
            mode = "claude.ai"
        else:
            mode = "unknown"
        print(json.dumps({"mode": mode, "transcript": t, "first_prompt": first_prompt(t) if t else None,
                          "transcript_modified_seconds_ago": int(time.time() - os.path.getmtime(t)) if t else None,
                          "sandbox_transcripts": os.path.isdir("/mnt/transcripts")}, indent=2))
        return 0

    if a.list:
        for p in candidates()[:30]:
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))}  "
                  f"{os.path.getsize(p) // 1024:>7} KB  {p}\n      {first_prompt(p)}")
        return 0

    bw = sk.BundleWriter()
    transcript = find_transcript(a.transcript)
    meta, messages, touched = {}, [], {}

    if transcript and os.path.isfile(transcript):
        rows = sk.read_jsonl(transcript)
        meta, messages, touched = sk.normalize_jsonl(rows, bw)
        if "local-agent-mode-sessions" in transcript or transcript.startswith("/sessions/"):
            meta["source"] = "cowork"
        if not a.no_raw:
            with open(transcript, "rb") as fh:
                bw.add(f"raw/{os.path.basename(transcript)}", fh.read(), "raw-transcript", original_path=transcript)
            side = os.path.join(os.path.dirname(transcript), os.path.splitext(os.path.basename(transcript))[0])
            for sub in ("subagents", "tool-results"):
                if os.path.isdir(os.path.join(side, sub)):
                    add_tree(bw, os.path.join(side, sub), f"raw/{sub}", f"raw-{sub}")
    elif os.path.isdir("/mnt/transcripts") or a.fallback_transcript:
        meta = {"title": a.title or "Claude chat", "source": "claude.ai-sandbox"}
        bw.warnings.append("No session .jsonl found. Transcript comes from the sandbox transcript files "
                           "or from Claude's own context, so pasted images may be missing. For a complete "
                           "claude.ai export use the Export Claude Session bookmark.")
        if os.path.isdir("/mnt/transcripts"):
            add_tree(bw, "/mnt/transcripts", "raw/transcripts", "raw-transcript")
    else:
        print("ERROR: no session transcript found. Run with --list, or pass --transcript PATH.", file=sys.stderr)
        return 2

    if a.title:
        meta["title"] = a.title
    meta["exported_at"] = sk.now_iso()

    # transcript.md
    if messages:
        md = sk.render_markdown(meta, messages, include_thinking=a.thinking)
    elif a.fallback_transcript and os.path.isfile(a.fallback_transcript):
        with open(a.fallback_transcript, encoding="utf-8", errors="replace") as fh:
            md = fh.read()
    else:
        texts = []
        for p in sorted(glob.glob("/mnt/transcripts/*")):
            if os.path.basename(p) == "journal.txt":
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                texts.append(fh.read())
        md = "\n\n".join(texts) or "(no transcript text found)"
    bw.add("transcript/transcript.md", md, "transcript")

    # handoff brief
    if a.brief_dir and os.path.isdir(a.brief_dir):
        for fn in sorted(os.listdir(a.brief_dir)):
            full = os.path.join(a.brief_dir, fn)
            if os.path.isfile(full):
                with open(full, "rb") as fh:
                    bw.add(f"brief/{fn}", fh.read(), "brief")
    else:
        bw.warnings.append("No handoff brief was included; the importer will rebuild one from the transcript.")

    # files the session created or edited
    n_edit = 0
    if touched and not a.no_edited_files:
        base = meta.get("cwd") or os.getcwd()
        for fp in touched:
            full = fp if os.path.isabs(fp) else os.path.join(base, fp)
            if not os.path.isfile(full) or is_bundle_artifact(full):
                continue
            if os.path.getsize(full) > MAX_FILE:
                bw.warnings.append(f"Skipped edited file {full}: over 25 MB")
                continue
            rel = os.path.relpath(full, base) if full.startswith(os.path.abspath(base) + os.sep) else full.lstrip("/")
            with open(full, "rb") as fh:
                bw.add(f"files/edited/{rel}", fh.read(), "edited-file", original_path=full)
            n_edit += 1

    # uploads / outputs (claude.ai or Cowork sandbox, Cowork session folder)
    n_io = 0
    io_dirs = [("/mnt/user-data/uploads", "files/uploads"), ("/mnt/user-data/outputs", "files/outputs")]
    if transcript and ".claude" in transcript:
        sess_root = transcript.split(os.sep + ".claude" + os.sep)[0]
        if sess_root != os.path.expanduser("~") and os.path.isdir(sess_root):
            io_dirs += [(os.path.join(sess_root, "uploads"), "files/uploads"),
                        (os.path.join(sess_root, "outputs"), "files/outputs")]
            audit = os.path.join(sess_root, "audit.jsonl")
            if os.path.isfile(audit) and not a.no_raw:
                with open(audit, "rb") as fh:
                    bw.add("raw/audit.jsonl", fh.read(), "raw-audit", original_path=audit)
    done = set()
    for src, dest in io_dirs:
        rs = os.path.realpath(src)
        if os.path.isdir(rs) and rs not in done:
            done.add(rs)
            n_io += add_tree(bw, rs, dest, dest.split("/")[-1].rstrip("s"), exclude=(is_bundle_artifact,))

    n_mem = collect_memory(bw, meta.get("cwd"), transcript if transcript and os.path.isfile(transcript) else None)

    for inc in a.include:
        inc = os.path.abspath(os.path.expanduser(inc))
        if os.path.isdir(inc):
            add_tree(bw, inc, f"files/included/{os.path.basename(inc)}", "included")
        elif os.path.isfile(inc):
            with open(inc, "rb") as fh:
                bw.add(f"files/included/{os.path.basename(inc)}", fh.read(), "included", original_path=inc)
        else:
            bw.warnings.append(f"--include {inc} not found")

    counts = sk.counts_for(messages)
    counts.update({"edited_files": n_edit, "workspace_files": n_io, "memory_files": n_mem,
                   "transcript_tokens_est": sk.est_text_tokens(md)})
    bw.add("README.md", sk.BUNDLE_README.format(title=meta.get("title") or "Claude session"), "readme")
    source = {k: meta.get(k) for k in ("source", "title", "conversation_id", "model", "created_at", "updated_at", "cwd", "entrypoint") if meta.get(k)}
    manifest = bw.manifest(source, counts)

    out_dir = a.out or ("/mnt/user-data/outputs" if os.path.isdir("/mnt/user-data/outputs") else os.getcwd())
    stamp = time.strftime("%Y%m%d-%H%M")
    out = os.path.join(os.path.expanduser(out_dir), f"{sk.slug(meta.get('title'), 50, 'claude-session')}-{stamp}.session.zip")
    bw.write_zip(out, manifest)

    print(json.dumps({"bundle": out, "bytes": os.path.getsize(out), "transcript": transcript,
                      "counts": counts, "warnings": bw.warnings}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
