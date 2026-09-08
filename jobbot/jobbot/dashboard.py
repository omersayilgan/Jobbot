"""Local review queue: an HTML dashboard backed by a tiny stdlib HTTP server.

Static HTML cannot write to the database, so the buttons POST back here.
Nothing is exposed beyond localhost.
"""
from __future__ import annotations

import html
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import db, letters
from .config import load_config

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Review Queue</title><style>
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#0f1115;color:#e6e8ec}
header{padding:22px 28px;border-bottom:1px solid #242833;position:sticky;top:0;background:#0f1115;z-index:5}
h1{margin:0 0 6px;font-size:19px;letter-spacing:-.01em}
.sub{color:#8b93a7;font-size:13px}
.wrap{max-width:1080px;margin:0 auto;padding:22px 28px 80px}
.tabs{display:flex;gap:6px;margin:16px 0 22px;flex-wrap:wrap}
.tab{padding:6px 13px;border:1px solid #2a2f3c;border-radius:99px;color:#9aa3b8;
     text-decoration:none;font-size:13px}
.tab.on{background:#2563eb;border-color:#2563eb;color:#fff}
.card{border:1px solid #242833;border-radius:12px;padding:16px 18px;margin-bottom:12px;background:#151822}
.card.hi{border-color:#2f5d3a}
.top{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}
.title{font-weight:600;font-size:16px;margin:0 0 3px}
.title a{color:#e6e8ec;text-decoration:none}.title a:hover{color:#7aa2ff}
.meta{color:#8b93a7;font-size:13px}
.score{font-weight:700;font-size:19px;padding:5px 11px;border-radius:9px;background:#1d2433;white-space:nowrap}
.s-hi{background:#173a25;color:#61d98a}.s-md{background:#3a3517;color:#e0c862}.s-lo{background:#2a2f3c;color:#9aa3b8}
.tags{margin:11px 0 0;display:flex;gap:6px;flex-wrap:wrap}
.tag{font-size:11.5px;padding:3px 9px;border-radius:6px;background:#1d2433;color:#9fb0d0}
details{margin-top:11px}summary{cursor:pointer;color:#8b93a7;font-size:13px}
details ul{margin:9px 0 0;padding-left:19px;color:#a8b0c3;font-size:13.5px}
.acts{margin-top:13px;display:flex;gap:7px;flex-wrap:wrap}
button{font:inherit;font-size:13px;padding:6px 13px;border-radius:7px;cursor:pointer;
       border:1px solid #2a2f3c;background:#1d2433;color:#cdd4e3}
button:hover{border-color:#3d465c}
button.go{background:#2563eb;border-color:#2563eb;color:#fff}
button.ok{background:#1c6b3a;border-color:#1c6b3a;color:#fff}
button.no{background:#2a2f3c}
.empty{color:#8b93a7;padding:40px;text-align:center}
.badge{font-size:11px;padding:2px 8px;border-radius:5px;background:#2a2f3c;color:#9aa3b8;margin-left:8px}
#toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#2563eb;color:#fff;
       padding:11px 20px;border-radius:9px;opacity:0;transition:.25s;pointer-events:none;font-size:14px}
#toast.show{opacity:1}
</style></head><body>
<header><h1>Job Review Queue</h1><div class="sub">__SUB__</div></header>
<div class="wrap"><div class="tabs">__TABS__</div>__CARDS__</div>
<div id="toast"></div>
<script>
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.className='show';
  setTimeout(()=>t.className='',1800);}
async function act(uid,what){
  const r=await fetch('/api/'+what,{method:'POST',headers:{'Content-Type':'application/json'},
                                   body:JSON.stringify({uid})});
  const d=await r.json();
  if(d.ok){toast(d.message);
    if(what!=='pack'){const c=document.getElementById('c-'+uid); if(c){c.style.opacity=.25;}}}
  else toast('Error: '+d.message);
}
</script></body></html>"""


def _card(row) -> str:
    matched = json.loads(row["matched"] or "{}")
    reasons = json.loads(row["reasons"] or "[]")
    s = row["score"]
    cls = "s-hi" if s >= 70 else ("s-md" if s >= 55 else "s-lo")
    e = html.escape

    tags = "".join(
        f'<span class="tag">{e(k)}: {e(", ".join(v[:3]))}</span>'
        for k, v in matched.items())
    why = "".join(f"<li>{e(r)}</li>" for r in reasons)
    badge = "" if row["status"] == "new" else f'<span class="badge">{e(row["status"])}</span>'

    return f"""
<div class="card {'hi' if s >= 70 else ''}" id="c-{row['uid']}">
  <div class="top">
    <div>
      <p class="title"><a href="{e(row['url'])}" target="_blank" rel="noopener">{e(row['title'])}</a>{badge}</p>
      <div class="meta">{e(row['company'])} &middot; {e(row['location'])} &middot; {e(row['source'])}
           {' &middot; ' + e(row['posted_at']) if row['posted_at'] else ''}</div>
    </div>
    <div class="score {cls}">{s}</div>
  </div>
  <div class="tags">{tags}</div>
  <details><summary>Why this matched ({len(reasons)} signals)</summary><ul>{why}</ul></details>
  <div class="acts">
    <button class="go" onclick="window.open('{e(row['url'])}','_blank')">Open posting</button>
    <button class="ok" onclick="act('{row['uid']}','pack')">Build application pack</button>
    <button onclick="act('{row['uid']}','applied')">Mark applied</button>
    <button class="no" onclick="act('{row['uid']}','skipped')">Skip</button>
  </div>
</div>"""


def render(conn, status: str | None, min_score: int) -> str:
    rows = db.query(conn, status=status, min_score=min_score, limit=300)
    st = db.stats(conn)
    counts = " · ".join(f"{k}: {v}" for k, v in sorted(st.items())) or "no jobs yet"

    tabs = []
    for label, key in (("Review queue", "new"), ("Shortlisted", "shortlisted"),
                       ("Applied", "applied"), ("Interview", "interview"),
                       ("Skipped", "skipped"), ("All", "")):
        on = "on" if (key or None) == status else ""
        tabs.append(f'<a class="tab {on}" href="/?status={key}">{label}</a>')

    cards = "".join(_card(r) for r in rows) or \
        '<div class="empty">Nothing here. Run <code>python3 run.py fetch</code> first.</div>'

    return (PAGE.replace("__SUB__", f"{len(rows)} shown &middot; {counts}")
                .replace("__TABS__", "".join(tabs))
                .replace("__CARDS__", cards))


class Handler(BaseHTTPRequestHandler):
    conn = None
    cfg: dict = {}

    def log_message(self, *a):        # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        status = "new"
        if "?" in self.path:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            status = (q.get("status", ["new"])[0]) or None
        html_out = render(self.conn, status, self.cfg["filters"]["min_score"])
        self._send(200, html_out.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        uid = json.loads(self.rfile.read(length) or b"{}").get("uid", "")
        action = self.path.rsplit("/", 1)[-1]
        row = db.get(self.conn, uid)

        if not row:
            return self._send(404, b'{"ok":false,"message":"unknown job"}', "application/json")
        try:
            if action == "pack":
                folder = letters.build_pack(row, self.cfg)
                db.set_status(self.conn, uid, "shortlisted")
                msg = f"Pack ready: {folder.split('applications/')[-1]}"
            else:
                db.set_status(self.conn, uid, action)
                msg = f"Marked {action}"
            payload = json.dumps({"ok": True, "message": msg})
        except Exception as exc:
            payload = json.dumps({"ok": False, "message": str(exc)})
        self._send(200, payload.encode("utf-8"), "application/json")


def serve(port: int = 8765, open_browser: bool = True):
    cfg = load_config()
    Handler.conn = db.connect()
    Handler.cfg = cfg
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Review queue running at {url}   (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
