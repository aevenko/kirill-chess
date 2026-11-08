// Admin API for kirillchess.com
// Runs as a Vercel serverless function. The GitHub token never reaches the browser.
//
// Environment variables (set in Vercel → Project → Settings → Environment Variables):
//   GITHUB_TOKEN         fine-grained token, repo aevenko/kirill-chess, Contents: read & write
//   ADMIN_PASSWORD_HASH  (optional) sha256 hex of the admin password; defaults to the existing site password
//   SESSION_SECRET       (optional) signs login sessions; derived from GITHUB_TOKEN if not set

const crypto = require('crypto');

const OWNER = 'aevenko';
const REPO = 'kirill-chess';
const BRANCH = 'main';
const SESSION_HOURS = 12;
const GH = 'https://api.github.com/repos/' + OWNER + '/' + REPO;

// very small in-memory brute-force brake (per warm instance)
const failures = new Map();
const DEFAULT_PASSWORD_HASH = 'bfe9586bdca203e0a6f62f3bde29dfa7245be81de9942ba05a45159ff3eeeb3a';
function passwordHash() { return (process.env.ADMIN_PASSWORD_HASH || DEFAULT_PASSWORD_HASH).toLowerCase(); }
function sessionKey() { return process.env.SESSION_SECRET || crypto.createHash('sha256').update('kc-session|' + (process.env.GITHUB_TOKEN || '')).digest('hex'); }

function sha256(s) { return crypto.createHash('sha256').update(String(s)).digest('hex'); }
function hmac(s) { return crypto.createHmac('sha256', sessionKey()).update(s).digest('hex'); }
function safeEq(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}
function makeSession() {
  const exp = Date.now() + SESSION_HOURS * 3600 * 1000;
  return exp + '.' + hmac('kc-admin.' + exp);
}
function checkSession(tok) {
  if (!tok || typeof tok !== 'string' || tok.indexOf('.') < 0) return false;
  const [exp, sig] = tok.split('.');
  if (!(+exp > Date.now())) return false;
  return safeEq(sig, hmac('kc-admin.' + exp));
}

async function gh(path, opts = {}) {
  const r = await fetch(GH + path, {
    ...opts,
    headers: {
      'Authorization': 'Bearer ' + process.env.GITHUB_TOKEN,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'kirillchess-admin',
      ...(opts.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
  const text = await r.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  if (!r.ok) {
    const err = new Error('GitHub ' + r.status + ': ' + (data && data.message ? data.message : text).toString().slice(0, 200));
    err.status = r.status; throw err;
  }
  return data;
}

async function readDataJson(ref) {
  const f = await gh('/contents/data.json?ref=' + encodeURIComponent(ref || BRANCH));
  const json = JSON.parse(Buffer.from(f.content, 'base64').toString('utf8'));
  return { json, sha: f.sha };
}

// changes: [{ path: ['about','para1_en'], value: ... }]  (path length 1..3)
function applyChanges(target, changes) {
  for (const c of changes || []) {
    if (!Array.isArray(c.path) || !c.path.length || c.path.length > 3) continue;
    if (c.path.some(k => typeof k !== 'string' || k === '__proto__' || k === 'constructor' || k === 'prototype')) continue;
    let o = target;
    for (let i = 0; i < c.path.length - 1; i++) {
      const k = c.path[i];
      if (typeof o[k] !== 'object' || o[k] === null || Array.isArray(o[k])) o[k] = {};
      o = o[k];
    }
    const last = c.path[c.path.length - 1];
    if (c.value === undefined) delete o[last]; else o[last] = c.value;
  }
  return target;
}

function safePhotoName(n) {
  const s = String(n || '').replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 80);
  return /\.(jpe?g|png|webp)$/i.test(s) ? s : null;
}

async function publish(changes, photos, message) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const ref = await gh('/git/ref/heads/' + BRANCH);
    const headSha = ref.object.sha;
    const head = await gh('/git/commits/' + headSha);
    const { json } = await readDataJson(headSha);
    applyChanges(json, changes);
    const dataBlob = await gh('/git/blobs', { method: 'POST', body: JSON.stringify({ content: JSON.stringify(json, null, 2) + '\n', encoding: 'utf-8' }) });
    const tree = [{ path: 'data.json', mode: '100644', type: 'blob', sha: dataBlob.sha }];
    for (const p of photos || []) {
      const name = safePhotoName(p.name);
      if (name && /^[0-9a-f]{40}$/.test(p.sha || '')) tree.push({ path: 'photos/' + name, mode: '100644', type: 'blob', sha: p.sha });
    }
    const newTree = await gh('/git/trees', { method: 'POST', body: JSON.stringify({ base_tree: head.tree.sha, tree }) });
    const commit = await gh('/git/commits', { method: 'POST', body: JSON.stringify({
      message: message || 'Admin: update site', tree: newTree.sha, parents: [headSha],
    }) });
    try {
      await gh('/git/refs/heads/' + BRANCH, { method: 'PATCH', body: JSON.stringify({ sha: commit.sha, force: false }) });
      return commit.sha;
    } catch (e) {
      if (e.status === 422 && attempt < 2) continue; // someone else pushed (e.g. auto-update) — redo on top
      throw e;
    }
  }
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') { res.status(405).json({ error: 'POST only' }); return; }
  if (!process.env.GITHUB_TOKEN) {
    res.status(500).json({ error: 'Сервер ещё не настроен: в Vercel не добавлен GITHUB_TOKEN.' }); return;
  }
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { body = {}; } }
  body = body || {};
  const ip = (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'x';

  try {
    if (body.action === 'login') {
      const f = failures.get(ip) || { n: 0, t: 0 };
      if (f.n >= 5 && Date.now() - f.t < 10 * 60 * 1000) { res.status(429).json({ error: 'Too many attempts. Try again in 10 minutes.' }); return; }
      if (safeEq(sha256(body.password || ''), passwordHash())) {
        failures.delete(ip);
        res.status(200).json({ session: makeSession() }); return;
      }
      failures.set(ip, { n: f.n + 1, t: Date.now() });
      await new Promise(r => setTimeout(r, 800));
      res.status(401).json({ error: 'Wrong password' }); return;
    }

    if (!checkSession(body.session)) { res.status(401).json({ error: 'Session expired. Please log in again.' }); return; }

    if (body.action === 'check') { res.status(200).json({ ok: true }); return; }

    if (body.action === 'load') {
      const { json, sha } = await readDataJson(BRANCH);
      res.status(200).json({ data: json, sha }); return;
    }

    if (body.action === 'upload') {
      // stores the photo as a git blob; it becomes part of the site at the next publish
      const b64 = String(body.base64 || '').replace(/^data:[^,]+,/, '');
      if (!b64 || b64.length > 4.2 * 1024 * 1024) { res.status(400).json({ error: 'Photo is empty or too large' }); return; }
      const blob = await gh('/git/blobs', { method: 'POST', body: JSON.stringify({ content: b64, encoding: 'base64' }) });
      res.status(200).json({ sha: blob.sha }); return;
    }

    if (body.action === 'publish') {
      const sha = await publish(body.changes, body.photos, body.message);
      res.status(200).json({ ok: true, commit: sha }); return;
    }

    res.status(400).json({ error: 'Unknown action' });
  } catch (e) {
    res.status(e.status && e.status < 500 ? 502 : 500).json({ error: String(e.message || e) });
  }
};
