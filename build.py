#!/usr/bin/env python3
"""Assemble the session-transfer plugin from src/ and package it.

    python3 build.py

Outputs (release/):
  session-transfer-plugin.zip         upload in Customize > Plugins (chat, Cowork, Claude Code)
  export-session.zip            single skill, for Customize > Skills on claude.ai
  import-session.zip            single skill, for Customize > Skills on claude.ai
  install-bookmarklet.html      open in Chrome, drag the button to the bookmarks bar
"""

import json
import os
import re
import shutil
import sys
import zipfile
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
PLUGIN = os.path.join(HERE, "plugins", "session-transfer")
DOCS = os.path.join(HERE, "docs")
DIST = os.path.join(HERE, "release")
sys.path.insert(0, SRC)
import sessionkit as sk  # noqa: E402


def minify_js(code: str) -> str:
    code = re.sub(r"^/\*.*?\*/\s*", "", code, count=1, flags=re.S)  # header comment
    out = []
    for line in code.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        out.append(s)
    return "\n".join(out)


def build_capture() -> str:
    with open(os.path.join(SRC, "capture.js"), encoding="utf-8") as fh:
        code = fh.read()
    marker = "/*__BUNDLE_README__*/"
    start = code.index(marker)
    end = code.index(";", start)
    code = code[:start] + json.dumps(sk.BUNDLE_README) + code[end:]
    code = code.replace("var VERSION = '1.0.0';", f"var VERSION = '{sk.TOOL_VERSION}';")
    return code


def bookmarklet(code: str) -> str:
    return "javascript:" + quote(minify_js(code), safe="(){}[];,.=:!?'*+-_/<>|&$@~")


INSTALL_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Export Claude Session</title>
<style>
:root{--bg:#faf9f7;--fg:#1f1e1d;--muted:#5f5d58;--card:#fff;--line:#e5e2dc;--accent:#c96442;--accent-fg:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#1f1e1d;--fg:#f2f0eb;--muted:#b3afa6;--card:#2a2927;--line:#3a3835;--accent:#d97757;--accent-fg:#1f1e1d}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:720px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 28px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin:0 0 18px}
.bm{display:inline-block;background:var(--accent);color:var(--accent-fg);text-decoration:none;font-weight:600;padding:12px 18px;border-radius:999px;cursor:grab}
ol{padding-left:22px}li{margin:6px 0}code{background:var(--line);padding:1px 6px;border-radius:5px;font-size:14px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:8px 12px;cursor:pointer}
small{color:var(--muted)}
</style></head><body><main>
<h1>Export Claude Session</h1>
<p class="sub">Version __VERSION__. Saves a claude.ai chat, with every message, pasted image, file and artifact, to one .zip on your computer.</p>
<div class="card"><h2>1. Install (once)</h2>
<p>Show your bookmarks bar (Ctrl+Shift+B, or Cmd+Shift+B on Mac), then drag this button onto it:</p>
<p><a class="bm" id="bm" href="__HREF__">Export Claude Session</a></p>
<p><small>Can't drag? Click <button id="copy" type="button">Copy bookmark code</button>, add a new bookmark named "Export Claude Session", and paste the code as its URL.</small></p></div>
<div class="card"><h2>2. Export a chat</h2><ol>
<li>Open the chat on claude.ai in this browser.</li>
<li>Recommended: type <code>/export-session</code> in that chat. Claude writes a handoff brief (goals, decisions, where you left off, the memory it was using).</li>
<li>Click the <b>Export Claude Session</b> bookmark. A progress box appears top right, then the <code>.session.zip</code> downloads.</li></ol></div>
<div class="card"><h2>3. Continue in a new chat or Cowork task</h2><ol>
<li>Start a new chat or Cowork task with the session-transfer plugin installed.</li>
<li>Attach the zip and say <b>import this session</b>.</li></ol></div>
<div class="card"><h2>Privacy</h2><p>It runs only in your browser tab and reads claude.ai with your existing sign-in. Nothing is sent anywhere else. The zip contains the whole conversation, so keep it private.</p>
<p><small>It uses claude.ai's internal web API, the same one the site uses. If claude.ai changes it, the export can stop working until this tool is updated.</small></p></div>
</main><script>
document.getElementById('copy').onclick=function(){var t=document.getElementById('bm').getAttribute('href');
(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){document.getElementById('copy').textContent='Copied';},
function(){prompt('Copy this bookmark code:',t);});};
document.getElementById('bm').onclick=function(e){e.preventDefault();alert('Drag this button to your bookmarks bar, then click it while a claude.ai chat is open.');};
</script></body></html>
"""


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def zip_dir(root, out_zip, arc_prefix=""):
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fns in os.walk(root):
            dn[:] = sorted(d for d in dn if d != "__pycache__")
            for fn in sorted(fns):
                if fn.endswith(".pyc") or fn == ".DS_Store":
                    continue
                full = os.path.join(dp, fn)
                arc = os.path.join(arc_prefix, os.path.relpath(full, root)).replace(os.sep, "/")
                z.write(full, arc)


def main():
    exp = os.path.join(PLUGIN, "skills", "export-session")
    imp = os.path.join(PLUGIN, "skills", "import-session")
    for d in (os.path.join(exp, "scripts"), os.path.join(imp, "scripts")):
        shutil.rmtree(d, ignore_errors=True)
    copy(os.path.join(SRC, "sessionkit.py"), os.path.join(exp, "scripts", "sessionkit.py"))
    copy(os.path.join(SRC, "export_local.py"), os.path.join(exp, "scripts", "export_local.py"))
    copy(os.path.join(SRC, "sessionkit.py"), os.path.join(imp, "scripts", "sessionkit.py"))
    copy(os.path.join(SRC, "import_bundle.py"), os.path.join(imp, "scripts", "import_bundle.py"))
    copy(os.path.join(DOCS, "bundle-format.md"), os.path.join(exp, "references", "bundle-format.md"))
    copy(os.path.join(DOCS, "bundle-format.md"), os.path.join(imp, "references", "bundle-format.md"))

    capture = build_capture()
    with open(os.path.join(exp, "scripts", "capture.js"), "w", encoding="utf-8") as fh:
        fh.write(capture)
    href = bookmarklet(capture)
    html = INSTALL_HTML.replace("__HREF__", href.replace("&", "&amp;").replace('"', "&quot;")).replace("__VERSION__", sk.TOOL_VERSION)
    os.makedirs(os.path.join(exp, "assets"), exist_ok=True)
    with open(os.path.join(exp, "assets", "install-bookmarklet.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    shutil.rmtree(DIST, ignore_errors=True)
    os.makedirs(DIST)
    shutil.copy2(os.path.join(exp, "assets", "install-bookmarklet.html"), os.path.join(DIST, "install-bookmarklet.html"))
    zip_dir(PLUGIN, os.path.join(DIST, "session-transfer-plugin.zip"))
    zip_dir(exp, os.path.join(DIST, "export-session.zip"), "export-session")
    zip_dir(imp, os.path.join(DIST, "import-session.zip"), "import-session")
    print(f"bookmarklet: {len(href):,} chars")
    for fn in sorted(os.listdir(DIST)):
        print(f"{os.path.getsize(os.path.join(DIST, fn)):>9,}  release/{fn}")


if __name__ == "__main__":
    main()
