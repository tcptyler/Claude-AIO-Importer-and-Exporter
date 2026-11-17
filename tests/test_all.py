#!/usr/bin/env python3
"""End-to-end tests. Run from anywhere:  python3 tests/test_all.py

Rebuilds the plugin, then exercises the browser capture against a mock
claude.ai, the importer on every supported input, and the local exporter.
Browser tests need Node.js with Playwright and are skipped without them.
"""

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
SRC = os.path.join(ROOT, "src")
sys.path[:0] = [TESTS, SRC]
import mock_claude as mc  # noqa: E402
import sessionkit as sk  # noqa: E402

PLUGIN = os.path.join(ROOT, "plugins", "session-transfer")
IMPORT = [sys.executable, os.path.join(SRC, "import_bundle.py")]
EXPORT = [sys.executable, os.path.join(SRC, "export_local.py")]
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def generated_files():
    out = {}
    for dp, _dn, fns in os.walk(os.path.join(PLUGIN, "skills")):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, PLUGIN)
            if "/scripts/" in "/" + rel or "/assets/" in "/" + rel or rel.endswith("bundle-format.md"):
                with open(p, "rb") as fh:
                    out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_build():
    before = generated_files()
    r = run([sys.executable, os.path.join(ROOT, "build.py")])
    check("build succeeds", r.returncode == 0, r.stderr[-400:])
    after = generated_files()
    check("committed generated files match a fresh build", not before or before == after,
          ", ".join(sorted(k for k in after if before.get(k) != after.get(k)))[:300])
    for name in ("export-session", "import-session"):
        md = open(os.path.join(PLUGIN, "skills", name, "SKILL.md"), encoding="utf-8").read()
        fm = md.split("---")[1]
        desc = [ln for ln in fm.splitlines() if ln.startswith("description:")][0]
        check(f"{name} frontmatter valid", "name: " + name in fm and len(desc) < 1040 and "<" not in desc and ">" not in desc)
    r = run(["node", "--check", os.path.join(PLUGIN, "skills", "export-session", "scripts", "capture.js")])
    check("capture.js syntax", r.returncode == 0, r.stderr[-300:])


def playwright_ok():
    r = run(["node", "-e", "require('playwright')"], cwd=TESTS)
    return r.returncode == 0


def test_browser(tmp):
    if not playwright_ok():
        print("SKIP browser tests (Node.js with Playwright not available)")
        return None
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), mc.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = os.path.join(tmp, "capture.session.zip")
        r = run(["node", os.path.join(TESTS, "run_bookmarklet.js"), str(port),
                 os.path.join(ROOT, "release", "install-bookmarklet.html"), out], timeout=120)
        check("bookmark runs and downloads", r.returncode == 0 and os.path.isfile(out), (r.stderr or r.stdout)[-400:])
        if r.returncode == 0:
            info = json.loads(r.stdout)
            check("no page errors", not info["errors"], str(info["errors"]))
            check("no capture warnings", info["summary"] and not info["summary"]["warnings"], str(info.get("summary")))
        r2 = run(["node", os.path.join(TESTS, "run_raw.js"), str(port),
                  os.path.join(PLUGIN, "skills", "export-session", "scripts", "capture.js")], timeout=120)
        check("raw capture.js runs (Claude in Chrome style)", r2.returncode == 0 and '"done":true' in r2.stdout and '"error":null' in r2.stdout,
              (r2.stderr or r2.stdout)[-400:])
    finally:
        srv.shutdown()
    return out if os.path.isfile(out) else None


def test_import_capture(tmp, bundle):
    dest, pub = os.path.join(tmp, "r"), os.path.join(tmp, "pub")
    r = run(IMPORT + [bundle, "--out", dest, "--budget", "100000", "--publish-dir", pub])
    check("import of captured bundle", r.returncode == 0, r.stderr[-400:])
    plan = r.stdout
    z = zipfile.ZipFile(bundle)
    names = set(z.namelist())
    md = open(os.path.join(dest, "transcript", "transcript.md"), encoding="utf-8").read()
    check("zip CRCs valid", z.testzip() is None)
    check("all files verified", "MISMATCH" not in plan and "MISSING" not in plan and "verified by SHA-256" in plan)
    check("edited-away branch left out", "ABANDONED" not in md)
    check("six messages", md.count("\n### [") == 6)
    check("reasoning not in transcript", "secret reasoning" not in md)
    check("pasted image saved from preview", any(n.startswith("images/m0001-1-logo") and n.endswith(".png") for n in names))
    check("image linked to workspace original", "](../files/uploads/diagram.png)" in md)
    check("document saved", "attachments/m0003-1-brief.pdf" in names)
    check("pasted text saved", "attachments/m0001-notes.txt" in names)
    check("three artifact versions", all(f"artifacts/launch-plan/v00{i}.md" in names for i in (1, 2, 3)))
    check("artifact edit keeps $& literally", "$& kept" in z.read("artifacts/launch-plan/v002.md").decode())
    check("latest artifact is final", z.read("artifacts/launch-plan/latest.md").decode() == "# Plan v3\n\nAll done.")
    check("created file linked to workspace output", "](../files/outputs/report.md)" in md)
    check("handoff brief captured", {"brief/HANDOFF.md", "brief/MEMORY.md"} <= names)
    check("older session zips skipped", not any(n.endswith(".session.zip") for n in names))
    check("project instructions and knowledge", {"project/instructions.md", "project/knowledge/brand.md"} <= names)
    check("raw conversation kept", "raw/conversation.json" in names)
    check("publish folder has latest artifact and outputs",
          os.path.isfile(os.path.join(pub, "artifacts", "launch-plan.md")) and os.path.isfile(os.path.join(pub, "outputs", "report.md")))
    check("both images marked VIEW", plan.count(", VIEW") == 2)


def make_fixtures(tmp):
    json.dump(mc.CONV, open(os.path.join(tmp, "chat.json"), "w"))
    a = dict(mc.CONV)
    a.pop("current_leaf_message_uuid")
    a["chat_messages"] = [m for m in a["chat_messages"] if m["uuid"] != "m3"]
    b = {"uuid": "zzz", "name": "Grocery list", "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z",
         "chat_messages": [{"uuid": "x1", "sender": "human", "text": "eggs", "created_at": "2026-10-01T00:00:00Z", "content": []}]}
    with zipfile.ZipFile(os.path.join(tmp, "data-export.zip"), "w") as z:
        z.writestr("data-2026-11-13/conversations.json", json.dumps([a, b]))
    img = base64.b64encode(mc.png(20, 10)).decode()
    app = os.path.join(tmp, "app.py")
    open(app, "w").write("print(1)\n")
    rows = [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "s1", "cwd": tmp, "entrypoint": "cli", "timestamp": "2026-11-12T10:00:00Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "<system-reminder>hidden context</system-reminder>Fix this bug"},
                                                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}}]}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-11-12T10:00:05Z", "message": {"id": "m1", "role": "assistant", "model": "claude-test", "content": [{"type": "thinking", "thinking": "hmm"}]}},
        {"type": "assistant", "uuid": "a2", "timestamp": "2026-11-12T10:00:06Z", "message": {"id": "m1", "role": "assistant", "model": "claude-test", "content": [{"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": app, "content": "print(1)"}}]}},
        {"type": "user", "uuid": "u2", "timestamp": "2026-11-12T10:00:07Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "File written"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}}]}]}},
        {"type": "assistant", "uuid": "a3", "timestamp": "2026-11-12T10:00:09Z", "message": {"id": "m2", "role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": "Fixed in app.py."}]}},
        {"type": "user", "uuid": "u3", "isMeta": True, "timestamp": "2026-11-12T10:01:00Z", "message": {"role": "user", "content": "<system-reminder>meta</system-reminder>"}},
        {"type": "user", "uuid": "u4", "isCompactSummary": True, "timestamp": "2026-11-12T11:00:00Z", "message": {"role": "user", "content": "Summary: fixed bug in app.py."}},
        {"type": "attachment", "uuid": "x", "attachment": {"type": "date"}},
        {"type": "user", "uuid": "u5", "timestamp": "2026-11-12T11:00:01Z", "message": {"role": "user", "content": "Now add tests"}},
        {"type": "assistant", "uuid": "a5", "isSidechain": True, "timestamp": "2026-11-12T11:00:02Z", "message": {"id": "sub", "role": "assistant", "content": [{"type": "text", "text": "SUBAGENT TEXT"}]}},
        {"type": "assistant", "uuid": "a6", "timestamp": "2026-11-12T11:00:03Z", "message": {"id": "m3", "role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": "Tests added."}]}},
    ]
    os.makedirs(os.path.join(tmp, "proj"), exist_ok=True)
    with open(os.path.join(tmp, "proj", "s1.jsonl"), "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    with zipfile.ZipFile(os.path.join(tmp, "evil.zip"), "w") as z:
        z.writestr("../../escape.txt", "x")
    msgs = [{"n": i, "role": "user" if i % 2 else "assistant", "time": "2026-11-12T00:00:00Z",
             "blocks": [{"type": "text", "text": ("word " * 4000) + f"MARK{i}"}]} for i in range(1, 121)]
    bw = sk.BundleWriter()
    bw.add("transcript/transcript.md", sk.render_markdown({"title": "Big"}, msgs), "transcript")
    bw.write_zip(os.path.join(tmp, "big.session.zip"), bw.manifest({"source": "test", "title": "Big"}, {}))


def test_other_inputs(tmp):
    make_fixtures(tmp)
    r = run(IMPORT + [os.path.join(tmp, "chat.json"), "--out", os.path.join(tmp, "r1")])
    md = open(os.path.join(tmp, "r1", "transcript", "transcript.md"), encoding="utf-8").read() if r.returncode == 0 else ""
    check("bare claude.ai JSON imports", r.returncode == 0 and "ABANDONED" not in md, r.stderr[-300:])
    check("bare JSON rebuilds artifacts", os.path.isfile(os.path.join(tmp, "r1", "artifacts", "launch-plan", "latest.md")))

    r = run(IMPORT + [os.path.join(tmp, "data-export.zip"), "--out", os.path.join(tmp, "r2")])
    check("official export asks which chat (exit 3)", r.returncode == 3 and "Grocery list" in r.stdout)
    r = run(IMPORT + [os.path.join(tmp, "data-export.zip"), "--out", os.path.join(tmp, "r2b"), "--pick", "grocery"])
    check("official export with --pick", r.returncode == 0 and "Grocery list" in r.stdout, r.stderr[-300:])

    r = run(EXPORT + ["--transcript", os.path.join(tmp, "proj", "s1.jsonl"), "--out", os.path.join(tmp, "out3")])
    ok = r.returncode == 0
    info = json.loads(r.stdout) if ok else {}
    check("local export runs", ok, r.stderr[-300:])
    check("local export counts", info.get("counts", {}).get("images") == 2 and info.get("counts", {}).get("edited_files") == 1, str(info.get("counts")))
    if ok:
        r = run(IMPORT + [info["bundle"], "--out", os.path.join(tmp, "r3")])
        md = open(os.path.join(tmp, "r3", "transcript", "transcript.md"), encoding="utf-8").read() if r.returncode == 0 else ""
        check("local bundle imports and verifies", r.returncode == 0 and "6 of 6 files verified" in r.stdout, r.stdout[:300])
        check("system reminders stripped", "hidden context" not in md and "Fix this bug" in md)
        check("subagent and meta messages left out", "SUBAGENT" not in md and "meta" not in md.split("---", 2)[-1])
        check("compaction summary kept", "Context summary" in md and "fixed bug in app.py" in md)
        check("pasted image and screenshot", "](../images/m0001-001.png)" in md and "(tool screenshot)" in md)

    r = run(IMPORT + [os.path.join(tmp, "evil.zip"), "--out", os.path.join(tmp, "r4")])
    check("zip with escaping paths refused", r.returncode != 0 and not os.path.exists(os.path.join(tmp, "escape.txt")))

    r = run(IMPORT + [os.path.join(tmp, "big.session.zip"), "--out", os.path.join(tmp, "r5"), "--budget", "60000"])
    parts = [f for f in os.listdir(os.path.join(tmp, "r5", "transcript")) if f.startswith("part-")] if r.returncode == 0 else []
    check("large transcript split into parts", len(parts) > 30, str(len(parts)))
    check("PARTIAL mode reads first and latest parts", "Mode: **PARTIAL**" in r.stdout and "part-001.md` (~" in r.stdout
          and f"part-{len(parts):03d}.md" in r.stdout and r.stdout.count(") READ") >= 2)
    joined = "".join(open(os.path.join(tmp, "r5", "transcript", p), encoding="utf-8").read() for p in sorted(parts))
    check("no message lost across parts", all(f"MARK{i}" in joined for i in range(1, 121)))


def main():
    tmp = tempfile.mkdtemp(prefix="aio-test-")
    try:
        test_build()
        bundle = test_browser(tmp)
        if bundle:
            test_import_capture(tmp, bundle)
        test_other_inputs(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
