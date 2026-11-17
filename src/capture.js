/* Export Claude Session: browser capture for claude.ai
 *
 * Runs inside your signed-in claude.ai tab (as a bookmark, pasted in the
 * DevTools console, or driven by Claude in Chrome). It reads the open chat
 * through the same internal API the claude.ai page uses, so every message is
 * captured from first to last, even if the chat was auto-summarized. It also
 * saves every pasted or uploaded image, uploaded documents, every artifact
 * version, the chat's workspace files (uploads and files Claude created),
 * project instructions and knowledge, and the handoff brief written by the
 * export-session skill. Everything is packed into one .session.zip that your
 * browser downloads. Nothing is sent anywhere else.
 *
 * Progress and results are exposed on window.__sessionExport
 * ({running, done, status, summary, error, promise}).
 */
(function () {
  'use strict';
  var VERSION = '1.0.0';
  var FORMAT = 'claude-session-bundle';
  var BUNDLE_README = /*__BUNDLE_README__*/'# Claude session bundle\n\nThis zip is a complete export of one Claude conversation: {title}\n';

  if (window.__sessionExport && window.__sessionExport.running) {
    return;
  }
  var state = window.__sessionExport = {
    version: VERSION, running: true, done: false, status: 'starting', summary: null, error: null, promise: null
  };
  var opts = window.__SESSION_EXPORT_OPTIONS || {};
  var enc = new TextEncoder();
  var API = location.origin + '/api';
  var ROOT_PARENT = '00000000-0000-4000-8000-000000000000';
  var warnings = [];

  // ---------------------------------------------------------------- status box
  var box = null;
  function show(text, kind) {
    state.status = text;
    try {
      if (!box) {
        box = document.createElement('div');
        box.setAttribute('role', 'status');
        box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;max-width:380px;' +
          'padding:10px 14px;border-radius:10px;font:13px/1.4 system-ui,sans-serif;' +
          'box-shadow:0 4px 18px rgba(0,0,0,.25);white-space:pre-wrap;cursor:pointer';
        box.title = 'Click to close';
        box.onclick = function () { box.remove(); box = null; };
        document.body.appendChild(box);
      }
      var colors = { work: ['#1f2937', '#f9fafb'], ok: ['#065f46', '#ecfdf5'], warn: ['#92400e', '#fffbeb'], err: ['#991b1b', '#fef2f2'] };
      var c = colors[kind || 'work'];
      box.style.background = c[0];
      box.style.color = c[1];
      box.textContent = 'Export Claude Session\n' + text;
    } catch (e) { /* no DOM: ignore */ }
  }
  function warn(msg) { warnings.push(msg); }

  // ------------------------------------------------------------------- helpers
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function short(u) { return String(u).replace(location.origin, '').split('?')[0]; }

  async function req(url, kind, tries) {
    kind = kind || 'json';
    tries = tries || 4;
    for (var i = 0; i < tries; i++) {
      var r;
      try {
        r = await fetch(url, { credentials: 'include', headers: kind === 'json' ? { Accept: 'application/json' } : {} });
      } catch (e) {
        if (i === tries - 1) throw e;
        await sleep(600 * Math.pow(2, i));
        continue;
      }
      if (r.status === 429 || r.status >= 500) {
        await sleep(800 * Math.pow(2, i));
        continue;
      }
      if (!r.ok) {
        var err = new Error('HTTP ' + r.status + ' for ' + short(url));
        err.status = r.status;
        throw err;
      }
      if (kind === 'json') {
        var ct = r.headers.get('content-type') || '';
        if (ct.indexOf('json') < 0) throw new Error('Expected JSON from ' + short(url) + ' (are you signed in?)');
        return r.json();
      }
      return new Uint8Array(await r.arrayBuffer());
    }
    throw new Error('Gave up after retries: ' + short(url));
  }

  function slug(s, max, dflt) {
    var out = String(s || '').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-._]+|[-._]+$/g, '').toLowerCase();
    out = out.slice(0, max || 60).replace(/[-._]+$/g, '');
    return out || dflt || 'item';
  }
  function safeName(name, dflt) {
    var base = String(name || '').replace(/\\/g, '/').split('/').pop();
    base = base.replace(/[\x00-\x1f<>:"|?*]+/g, '_').replace(/^[ .]+|[ .]+$/g, '');
    return base.slice(0, 120) || dflt || 'file';
  }
  function pad(n) { return String(n).padStart(4, '0'); }
  function fmtTime(ts) {
    if (!ts) return 'time unknown';
    var d = new Date(ts);
    if (isNaN(d)) return String(ts).slice(0, 19);
    return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  }
  function oneLine(s, limit) {
    s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    limit = limit || 240;
    return s.length <= limit ? s : s.slice(0, limit - 3) + '...';
  }
  function sniffExt(d, fallback) {
    if (d[0] === 0x89 && d[1] === 0x50) return 'png';
    if (d[0] === 0xff && d[1] === 0xd8) return 'jpg';
    if (d[0] === 0x47 && d[1] === 0x49 && d[2] === 0x46) return 'gif';
    if (d[0] === 0x52 && d[1] === 0x49 && d[8] === 0x57 && d[9] === 0x45) return 'webp';
    if (d[0] === 0x25 && d[1] === 0x50 && d[2] === 0x44 && d[3] === 0x46) return 'pdf';
    return fallback || 'bin';
  }
  function stem(name) { var n = safeName(name, 'file'); var i = n.lastIndexOf('.'); return i > 0 ? n.slice(0, i) : n; }
  function absUrl(u) { try { return new URL(u, location.origin).href; } catch (e) { return null; } }

  var ARTIFACT_EXT = { 'text/html': 'html', 'text/markdown': 'md', 'image/svg+xml': 'svg',
    'application/vnd.ant.mermaid': 'mmd', 'application/vnd.ant.react': 'jsx', 'text/plain': 'txt' };
  var LANG_EXT = { python: 'py', javascript: 'js', typescript: 'ts', jsx: 'jsx', tsx: 'tsx', html: 'html', css: 'css',
    json: 'json', bash: 'sh', shell: 'sh', sh: 'sh', sql: 'sql', yaml: 'yaml', yml: 'yaml', markdown: 'md', java: 'java',
    go: 'go', rust: 'rs', c: 'c', cpp: 'cpp', 'c++': 'cpp', csharp: 'cs', 'c#': 'cs', ruby: 'rb', php: 'php',
    swift: 'swift', kotlin: 'kt', powershell: 'ps1', xml: 'xml', toml: 'toml' };
  function artifactExt(type, lang) {
    if (ARTIFACT_EXT[type]) return ARTIFACT_EXT[type];
    if (lang && LANG_EXT[String(lang).toLowerCase()]) return LANG_EXT[String(lang).toLowerCase()];
    return 'txt';
  }
  function toolSummary(inp) {
    if (!inp || typeof inp !== 'object') return oneLine(inp, 200);
    var keys = ['description', 'query', 'command', 'file_path', 'path', 'url', 'prompt', 'pattern', 'title'];
    for (var i = 0; i < keys.length; i++) {
      var v = inp[keys[i]];
      if (typeof v === 'string' && v.trim()) return oneLine(v, 200);
    }
    var small = {};
    Object.keys(inp).forEach(function (k) {
      var v = inp[k];
      if (['string', 'number', 'boolean'].indexOf(typeof v) >= 0 && String(v).length < 120) small[k] = v;
    });
    return Object.keys(small).length ? oneLine(JSON.stringify(small), 200) : '';
  }
  function resultSummary(content) {
    if (typeof content === 'string') return oneLine(content, 300);
    if (Array.isArray(content)) {
      return oneLine(content.filter(function (c) { return c && c.type === 'text'; }).map(function (c) { return c.text || ''; }).join(' '), 300);
    }
    return '';
  }

  // ------------------------------------------------------------- file store
  var files = []; // {path, data, role, meta}
  var used = Object.create(null);
  function unique(path) {
    path = path.replace(/\\/g, '/').split('/').filter(function (p) { return p && p !== '.' && p !== '..'; }).join('/') || 'file';
    if (!used[path]) { used[path] = 1; return path; }
    var dot = path.lastIndexOf('.');
    var hasExt = dot > path.lastIndexOf('/');
    var base = hasExt ? path.slice(0, dot) : path;
    var ext = hasExt ? path.slice(dot) : '';
    for (var i = 2; ; i++) {
      var cand = base + '-' + i + ext;
      if (!used[cand]) { used[cand] = 1; return cand; }
    }
  }
  function add(path, data, role, meta) {
    if (typeof data === 'string') data = enc.encode(data);
    var p = unique(path);
    files.push({ path: p, data: data, role: role, meta: meta || {} });
    return p;
  }

  // ------------------------------------------------------------------ zip
  var CRC = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(d) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < d.length; i++) c = CRC[(c ^ d[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function makeZip(entries) {
    if (entries.length > 65000) throw new Error('Too many files for one zip (' + entries.length + ')');
    var now = new Date();
    var dosTime = ((now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1)) & 0xFFFF;
    var dosDate = (((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()) & 0xFFFF;
    var chunks = [], central = [], offset = 0;
    entries.forEach(function (f) {
      var name = enc.encode(f.path);
      var crc = crc32(f.data), size = f.data.length;
      var lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true);
      lh.setUint16(8, 0, true); lh.setUint16(10, dosTime, true); lh.setUint16(12, dosDate, true);
      lh.setUint32(14, crc, true); lh.setUint32(18, size, true); lh.setUint32(22, size, true);
      lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
      chunks.push(new Uint8Array(lh.buffer), name, f.data);
      var ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true);
      ch.setUint16(8, 0x0800, true); ch.setUint16(10, 0, true); ch.setUint16(12, dosTime, true);
      ch.setUint16(14, dosDate, true); ch.setUint32(16, crc, true); ch.setUint32(20, size, true);
      ch.setUint32(24, size, true); ch.setUint16(28, name.length, true); ch.setUint16(30, 0, true);
      ch.setUint16(32, 0, true); ch.setUint16(34, 0, true); ch.setUint16(36, 0, true);
      ch.setUint32(38, 0, true); ch.setUint32(42, offset, true);
      central.push(new Uint8Array(ch.buffer), name);
      offset += 30 + name.length + size;
      if (offset > 0xFFFFFFFF) throw new Error('Export is larger than 4 GB');
    });
    var cdSize = central.reduce(function (a, b) { return a + b.length; }, 0);
    var end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true); end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
    return new Blob(chunks.concat(central, [new Uint8Array(end.buffer)]), { type: 'application/zip' });
  }
  async function sha256hex(data) {
    var h = new Uint8Array(await crypto.subtle.digest('SHA-256', data));
    return Array.prototype.map.call(h, function (b) { return b.toString(16).padStart(2, '0'); }).join('');
  }
  async function pool(items, n, fn) {
    var i = 0;
    async function worker() { while (i < items.length) { var k = i++; await fn(items[k], k); } }
    var ws = [];
    for (var j = 0; j < Math.min(n, items.length); j++) ws.push(worker());
    await Promise.all(ws);
  }

  // ---------------------------------------------------------- claude.ai API
  function conversationId() {
    if (opts.conversationId) return opts.conversationId;
    var m = location.pathname.match(/\/chat\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
    return m ? m[1] : null;
  }
  function cookieOrg() {
    var m = document.cookie.match(/(?:^|;\s*)lastActiveOrg=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }
  async function findConversation(cid) {
    var tried = [];
    var first = opts.orgId || cookieOrg();
    var orgs = first ? [first] : [];
    async function tryOrg(org) {
      tried.push(org);
      var url = API + '/organizations/' + org + '/chat_conversations/' + cid +
        '?tree=True&rendering_mode=messages&render_all_tools=true';
      return req(url);
    }
    for (var i = 0; i < orgs.length; i++) {
      try { return { org: orgs[i], conv: await tryOrg(orgs[i]) }; } catch (e) { /* try the others */ }
    }
    var list = await req(API + '/organizations');
    var ids = (Array.isArray(list) ? list : []).map(function (o) { return o && o.uuid; }).filter(Boolean);
    for (var j = 0; j < ids.length; j++) {
      if (tried.indexOf(ids[j]) >= 0) continue;
      try { return { org: ids[j], conv: await tryOrg(ids[j]) }; } catch (e) { /* next */ }
    }
    throw new Error('This chat was not found in any of your organizations. Are you signed in to the right account?');
  }
  function currentBranch(conv) {
    var msgs = conv.chat_messages || [];
    var byId = {};
    msgs.forEach(function (m) { if (m.uuid) byId[m.uuid] = m; });
    var leaf = conv.current_leaf_message_uuid, path = [], seen = {};
    while (leaf && byId[leaf] && !seen[leaf]) {
      seen[leaf] = 1;
      path.push(byId[leaf]);
      leaf = byId[leaf].parent_message_uuid;
    }
    if (path.length && (!leaf || leaf === ROOT_PARENT || !byId[leaf])) return path.reverse();
    if (conv.current_leaf_message_uuid) warn('Could not follow the current branch, so messages are in creation order and may include edited-away branches.');
    return msgs.slice().sort(function (a, b) { return (a.index || 0) - (b.index || 0); });
  }

  // ------------------------------------------------------------------- main
  async function main() {
    var cid = conversationId();
    if (!cid) throw new Error('Open the chat you want to export first (a claude.ai/chat/... page), then run this again.');
    show('Reading the conversation...');
    var found = await findConversation(cid);
    var org = found.org, conv = found.conv;
    var title = conv.name || 'Untitled chat';
    add('raw/conversation.json', JSON.stringify(conv, null, 1), 'raw-conversation');

    // workspace files (uploads, outputs Claude created, the handoff brief)
    show('Listing workspace files...');
    var wiggle = API + '/organizations/' + org + '/conversations/' + cid + '/wiggle';
    var wfiles = [];
    try {
      var listing = await req(wiggle + '/list-files');
      var raw = listing && (listing.files || listing.paths || listing);
      wfiles = (Array.isArray(raw) ? raw : []).map(function (f) { return typeof f === 'string' ? f : (f && (f.path || f.name)); })
        .filter(function (p) { return typeof p === 'string' && p && !/\/$/.test(p) && p.split('/').indexOf('..') < 0; });
      add('raw/workspace-files.json', JSON.stringify(wfiles, null, 1), 'raw-workspace-list');
    } catch (e) {
      warn('Workspace files unavailable (' + e.message + '). Normal when code execution is off for this chat.');
    }
    var byName = Object.create(null); // basename -> bundle path (originals)
    var briefCount = 0, wsCount = 0;
    await pool(wfiles, 4, async function (p) {
      var m = p.match(/^\/mnt\/user-data\/(uploads|outputs)\/(.+)$/);
      if (!m) return;
      var rel = m[2];
      if (/\.session\.zip$/i.test(rel)) return;
      var dest, role;
      if (m[1] === 'outputs' && /^session-export\//.test(rel)) {
        dest = 'brief/' + rel.replace(/^session-export\//, '');
        role = 'brief';
      } else {
        dest = 'files/' + m[1] + '/' + rel;
        role = m[1] === 'uploads' ? 'upload' : 'output';
      }
      try {
        var data = await req(wiggle + '/download-file?path=' + encodeURIComponent(p), 'bytes');
        var saved = add(dest, data, role, { original_path: p });
        if (role === 'brief') briefCount++; else wsCount++;
        byName[safeName(rel)] = saved;
        show('Downloaded ' + (briefCount + wsCount) + ' of ' + wfiles.length + ' workspace files...');
      } catch (e) {
        warn('Could not download ' + p + ': ' + e.message);
      }
    });
    if (!briefCount) {
      warn('No handoff brief found. For the best import, type /export-session in the chat first so Claude writes one, then run this bookmark again.');
    }

    // messages
    var branch = currentBranch(conv);
    var lines = [];
    var counts = { messages: branch.length, images: 0, images_missing: 0, attachments: 0, artifacts: 0, artifact_versions: 0, tool_calls: 0 };
    var artifacts = {}; // id -> {title,type,language,content,versions}
    var imageJobs = [];

    branch.forEach(function (m, idx) {
      var n = idx + 1;
      var who = m.sender === 'human' ? 'User' : 'Claude';
      var out = ['### [' + pad(n) + '] ' + who + ' · ' + fmtTime(m.created_at), ''];
      var seenFiles = {};
      (m.files_v2 || []).concat(m.files || []).forEach(function (f, k) {
        if (!f) return;
        var key = f.file_uuid || f.uuid || f.file_name || ('f' + k);
        if (seenFiles[key]) return;
        seenFiles[key] = 1;
        var name = f.file_name || ('file-' + (k + 1));
        var original = byName[safeName(name)];
        if (f.file_kind === 'image' || /^image\//.test(f.file_type || f.mime_type || '')) {
          var holder = { line: null };
          out.push(holder);
          out.push('');
          counts.images++;
          imageJobs.push({ n: n, k: k + 1, f: f, name: name, original: original, holder: holder });
        } else {
          var holder2 = { line: null };
          out.push(holder2);
          out.push('');
          counts.attachments++;
          imageJobs.push({ n: n, k: k + 1, f: f, name: name, original: original, holder: holder2, doc: true });
        }
      });
      (m.attachments || []).forEach(function (a, k) {
        if (!a) return;
        var name = a.file_name || ('pasted-text-' + (k + 1) + '.txt');
        var text = typeof a.extracted_content === 'string' ? a.extracted_content : '';
        if (!text) {
          out.push('> Attachment: ' + name + ' (no text captured)', '');
          return;
        }
        var fname = safeName(name, 'pasted-text.txt');
        if (!/\.(txt|md|markdown|csv|json)$/i.test(fname)) fname += '.txt';
        var p = add('attachments/m' + pad(n) + '-' + fname, text, 'attachment', { message: n, original_name: name });
        counts.attachments++;
        out.push('> Attachment: [' + name + '](../' + p + ') (' + text.length + ' chars of text)', '');
      });
      var content = m.content;
      if ((!content || !content.length) && m.text) content = [{ type: 'text', text: m.text }];
      (content || []).forEach(function (c) {
        if (!c) return;
        if (c.type === 'text' && c.text && c.text.trim()) {
          out.push(c.text.replace(/\s+$/, ''), '');
        } else if (c.type === 'tool_use') {
          var name = c.name || 'tool';
          var inp = c.input || {};
          if (name === 'artifacts' && typeof inp === 'object') {
            var id = inp.id || ('artifact-' + (Object.keys(artifacts).length + 1));
            var a = artifacts[id] || (artifacts[id] = { title: inp.title || id, type: inp.type, language: inp.language, content: '', versions: [] });
            var cmd = inp.command || 'create';
            if (inp.title) a.title = inp.title;
            if (inp.type) a.type = inp.type;
            if (inp.language) a.language = inp.language;
            if (cmd === 'update' && typeof inp.old_str === 'string') {
              var at = a.content.indexOf(inp.old_str);
              if (at >= 0) a.content = a.content.slice(0, at) + (inp.new_str || '') + a.content.slice(at + inp.old_str.length);
              else warn('Artifact "' + a.title + '" update in message ' + n + ' did not match; that version may be off.');
            } else if (typeof inp.content === 'string') {
              a.content = inp.content;
            }
            var v = a.versions.length + 1;
            var vp = add('artifacts/' + slug(a.title) + '/v' + String(v).padStart(3, '0') + '.' + artifactExt(a.type, a.language),
              a.content, 'artifact-version', { artifact_id: id, title: a.title, version: v, message: n });
            a.versions.push(vp);
            counts.artifact_versions++;
            out.push('> Artifact ' + cmd + ' v' + v + ': "' + a.title + '" -> [' + vp + '](../' + vp + ')', '');
            return;
          }
          var keys = ['content', 'file_text', 'widget_code', 'code', 'html'];
          var key = keys.filter(function (k2) { return typeof inp[k2] === 'string' && inp[k2].length > 200; })[0];
          if (key) {
            var fname2 = safeName(inp.path || inp.file_path || inp.title || (name + '.txt'));
            var existing = byName[fname2];
            var tp = existing || add('artifacts/tool-' + slug(name) + '/m' + pad(n) + '-' + fname2, inp[key], 'tool-content', { tool: name, message: n });
            out.push('> Artifact ' + name + ': "' + fname2 + '" -> [' + tp + '](../' + tp + ')', '');
            return;
          }
          counts.tool_calls++;
          out.push(('> Tool · ' + name + ': ' + toolSummary(inp)).replace(/\s+$/, ''), '');
        } else if (c.type === 'tool_result') {
          var s = resultSummary(c.content);
          if (s) out.push('> ' + (c.is_error ? 'Error' : 'Result') + ': ' + s, '');
        }
      });
      lines.push(out);
    });

    // images and documents attached to messages
    var done = 0;
    show('Saving ' + imageJobs.length + ' images and files...');
    await pool(imageJobs, 4, async function (job) {
      var f = job.f, p = job.original, note = '';
      if (!p) {
        var url = job.doc
          ? (f.document_asset && f.document_asset.url)
          : ((f.preview_asset && f.preview_asset.url) || f.preview_url || (f.thumbnail_asset && f.thumbnail_asset.url) || f.thumbnail_url);
        if (url && absUrl(url)) {
          try {
            var data = await req(absUrl(url), 'bytes');
            var ext = sniffExt(data, job.doc ? 'bin' : 'png');
            var folder = job.doc ? 'attachments/' : 'images/';
            var asset = job.doc ? f.document_asset : (f.preview_asset || f.thumbnail_asset);
            p = add(folder + 'm' + pad(job.n) + '-' + job.k + '-' + slug(stem(job.name), 60, 'file') + '.' + ext, data,
              job.doc ? 'attachment' : 'image',
              { message: job.n, original_name: job.name, width: asset && asset.image_width, height: asset && asset.image_height,
                note: job.doc ? null : (f.preview_url || f.preview_asset ? 'preview copy' : 'thumbnail copy') });
            if (!job.doc && !f.preview_url && !f.preview_asset) note = 'thumbnail only';
          } catch (e) {
            warn('Could not save ' + job.name + ' from message ' + job.n + ': ' + e.message);
          }
        }
      }
      if (job.doc) {
        job.holder.line = p ? '> Attachment: [' + job.name + '](../' + p + ')' : '> Attachment: ' + job.name + ' (file not captured; see extracted text if any)';
      } else if (p) {
        job.holder.line = '![' + job.name.replace(/[\[\]]/g, '') + '](../' + p + ')' + (note ? ' (' + note + ')' : '');
      } else {
        counts.images_missing++;
        job.holder.line = '> Image: ' + job.name + ' (not captured)';
      }
      done++;
      show('Saved ' + done + ' of ' + imageJobs.length + ' images and files...');
    });

    Object.keys(artifacts).forEach(function (id) {
      var a = artifacts[id];
      if (!a.versions.length) return;
      counts.artifacts++;
      add('artifacts/' + slug(a.title) + '/latest.' + artifactExt(a.type, a.language), a.content, 'artifact-latest',
        { artifact_id: id, title: a.title, versions: a.versions.length });
    });

    // project instructions and knowledge (best effort)
    var projectId = conv.project_uuid || (conv.project && conv.project.uuid);
    var projectName = null;
    if (projectId) {
      show('Reading project instructions and knowledge...');
      try {
        var proj = await req(API + '/organizations/' + org + '/projects/' + projectId);
        projectName = proj.name || null;
        add('raw/project.json', JSON.stringify(proj, null, 1), 'raw-project');
        var instr = proj.prompt_template || proj.instructions || '';
        if (instr) add('project/instructions.md', '# Project instructions: ' + (proj.name || '') + '\n\n' + instr, 'project-instructions');
        if (proj.description) add('project/description.md', proj.description, 'project-description');
      } catch (e) {
        warn('Project details unavailable: ' + e.message);
      }
      try {
        var docs = await req(API + '/organizations/' + org + '/projects/' + projectId + '/docs');
        (Array.isArray(docs) ? docs : []).forEach(function (d) {
          if (!d || typeof d.content !== 'string') return;
          var fn = safeName(d.file_name || 'knowledge.txt');
          if (!/\.[A-Za-z0-9]{1,6}$/.test(fn)) fn += '.txt';
          add('project/knowledge/' + fn, d.content, 'project-knowledge');
        });
      } catch (e) {
        warn('Project knowledge unavailable: ' + e.message);
      }
    }

    // transcript
    var meta = { title: title, source: 'claude.ai', conversation_id: cid, model: conv.model || null,
      created_at: conv.created_at || null, updated_at: conv.updated_at || null,
      url: location.origin + '/chat/' + cid, exported_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z') };
    var fm = ['---'];
    ['title', 'source', 'conversation_id', 'model', 'created_at', 'updated_at', 'url', 'exported_at'].forEach(function (k) {
      if (meta[k]) fm.push(k + ': ' + JSON.stringify(String(meta[k])));
    });
    fm.push('messages: ' + branch.length, '---');
    var md = fm.join('\n') + '\n\n# ' + title + '\n\n' +
      'Full transcript of the current branch. Images, attachments and artifacts are linked by relative path inside this bundle.\n\n' +
      lines.map(function (out) {
        return out.map(function (l) { return typeof l === 'string' ? l : (l.line || ''); }).join('\n').replace(/\s+$/, '') + '\n';
      }).join('\n');
    add('transcript/transcript.md', md, 'transcript');
    add('README.md', BUNDLE_README.replace('{title}', title), 'readme');

    // manifest
    show('Checksumming ' + files.length + ' files...');
    var entries = [];
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var e = { path: f.path, bytes: f.data.length, sha256: await sha256hex(f.data), role: f.role };
      Object.keys(f.meta).forEach(function (k) { var v = f.meta[k]; if (v !== null && v !== undefined && v !== '') e[k] = v; });
      entries.push(e);
    }
    counts.workspace_files = wsCount;
    counts.transcript_tokens_est = Math.ceil(md.length / 3.6);
    var source = { source: 'claude.ai', title: title, conversation_id: cid, model: meta.model, created_at: meta.created_at,
      updated_at: meta.updated_at, url: meta.url, project_id: projectId || undefined, project_name: projectName || undefined };
    var manifest = { format: FORMAT, version: 1, created_by: 'session-transfer ' + VERSION + ' (browser capture)',
      exported_at: meta.exported_at, source: source, counts: counts, warnings: warnings, files: entries };
    var zipEntries = [{ path: 'manifest.json', data: enc.encode(JSON.stringify(manifest, null, 2)) }].concat(files);

    show('Building zip...');
    var blob = makeZip(zipEntries);
    var d = new Date();
    var stamp = d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0') + '-' +
      String(d.getHours()).padStart(2, '0') + String(d.getMinutes()).padStart(2, '0');
    var fileName = slug(title, 50, 'claude-chat') + '-' + stamp + '.session.zip';
    if (opts.download !== false) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 120000);
    }
    state.blob = blob;
    return { file: fileName, bytes: blob.size, counts: counts, warnings: warnings, brief: briefCount > 0 };
  }

  state.promise = main().then(function (summary) {
    state.summary = summary;
    state.running = false;
    state.done = true;
    var c = summary.counts;
    var msg = 'Done: ' + summary.file + '\n' + c.messages + ' messages, ' + c.images + ' images, ' + c.attachments +
      ' attachments, ' + c.artifacts + ' artifacts, ' + c.workspace_files + ' workspace files' +
      (summary.brief ? ', handoff brief included' : '') +
      (summary.warnings.length ? '\n\nNotes:\n- ' + summary.warnings.join('\n- ') : '');
    show(msg, summary.warnings.length ? 'warn' : 'ok');
    try { console.info('[session-export]', summary); } catch (e) { /* ignore */ }
    return summary;
  }, function (err) {
    state.error = String(err && err.message || err);
    state.running = false;
    state.done = true;
    show('Export failed: ' + state.error, 'err');
    try { console.error('[session-export]', err); } catch (e) { /* ignore */ }
    return { error: state.error };
  });
})();
