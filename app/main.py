import os, json, time, shutil, zipfile, signal, subprocess, threading, secrets
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends

DATA = Path(os.getenv("DATA_DIR", "/var/data"))
BOTS = DATA / "bots"
LOGS = DATA / "logs"
META = DATA / "bots.json"
BOTS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    raise RuntimeError("Set ADMIN_PASSWORD in Render environment variables before starting.")
app = FastAPI(title="BotPilot Private Hosting")
security = HTTPBasic()
processes = {}
process_lock = threading.RLock()
monitor_started = False

def auth(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Login required", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def read_meta():
    try:
        return json.loads(META.read_text())
    except Exception:
        return {}

def write_meta(data):
    tmp = META.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(META)

def bot_dir(bot_id): return BOTS / bot_id
def log_path(bot_id): return LOGS / f"{bot_id}.log"

def append_log(bot_id, line):
    with log_path(bot_id).open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"[{datetime.utcnow().isoformat()}Z] {line}\n")

def command_for(bot):
    root = bot_dir(bot["id"])
    entry = bot["entry"]
    if entry.endswith(".php"):
        return ["php", "-d", "display_errors=1", str(root / entry)]
    if entry.endswith(".py"):
        return ["python", "-u", str(root / entry)]
    raise ValueError("Entry must be a .py or .php file")

def start_bot(bot_id, recovery=False):
    with process_lock:
        meta = read_meta()
        bot = meta.get(bot_id)
        if not bot: raise ValueError("Bot not found")
        current = processes.get(bot_id)
        if current and current.poll() is None:
            return
        if not recovery:
            bot["restart_count"] = 0
        bot["status"] = "starting"
        bot["last_started"] = datetime.utcnow().isoformat() + "Z"
        write_meta(meta)
        lp = log_path(bot_id)
        lp.parent.mkdir(parents=True, exist_ok=True)
        log_file = lp.open("a", encoding="utf-8", errors="replace")
        try:
            p = subprocess.Popen(
                command_for(bot), cwd=str(bot_dir(bot_id)),
                stdout=log_file, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )
        except Exception as e:
            log_file.close()
            bot["status"] = "error"
            bot["last_error"] = str(e)
            write_meta(meta)
            append_log(bot_id, f"START ERROR: {e}")
            raise
        processes[bot_id] = p
        bot["status"] = "running"
        bot["pid"] = p.pid
        bot["last_error"] = ""
        write_meta(meta)
        append_log(bot_id, f"Started process PID={p.pid}; command={command_for(bot)}")

def stop_bot(bot_id):
    with process_lock:
        meta = read_meta()
        bot = meta.get(bot_id)
        if not bot: raise ValueError("Bot not found")
        p = processes.get(bot_id)
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                try: p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait(timeout=3)
            except ProcessLookupError:
                pass
        processes.pop(bot_id, None)
        bot["status"] = "stopped"
        bot.pop("pid", None)
        write_meta(meta)
        append_log(bot_id, "Stopped by user")

def monitor():
    while True:
        time.sleep(5)
        with process_lock:
            meta = read_meta()
            changed = False
            for bot_id, bot in meta.items():
                p = processes.get(bot_id)
                if p is None or p.poll() is None:
                    continue
                code = p.returncode
                processes.pop(bot_id, None)
                bot.pop("pid", None)
                append_log(bot_id, f"Process exited with code {code}")
                # Crash recovery: restart at most 5 times in a rolling simple counter.
                count = int(bot.get("restart_count", 0))
                if bot.get("desired_state") == "running" and count < 5:
                    bot["restart_count"] = count + 1
                    bot["status"] = "recovering"
                    changed = True
                    write_meta(meta)
                    threading.Thread(target=_delayed_restart, args=(bot_id, count + 1), daemon=True).start()
                else:
                    bot["status"] = "stopped" if bot.get("desired_state") != "running" else "crashed"
                    changed = True
            if changed: write_meta(meta)

def _delayed_restart(bot_id, attempt):
    time.sleep(min(30, 2 ** attempt))
    try: start_bot(bot_id, recovery=True)
    except Exception as e: append_log(bot_id, f"RECOVERY ERROR: {e}")

@app.on_event("startup")
def startup():
    global monitor_started
    if not monitor_started:
        threading.Thread(target=monitor, daemon=True).start()
        monitor_started = True

def page(body, title="BotPilot"):
    return HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#080b14;--panel:#111827;--line:#263244;--text:#eef2ff;--muted:#9caac0;--accent:#7c5cff;}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(150deg,#080b14,#11172a);color:var(--text);font:16px system-ui,Arial}}
main{{max-width:980px;margin:auto;padding:22px}}h1{{margin:0;font-size:28px}}.sub{{color:var(--muted);margin:5px 0 22px}}
.card{{background:#101827;border:1px solid var(--line);border-radius:16px;padding:17px;margin:14px 0;box-shadow:0 8px 30px #0003}}
input,select,button{{font:inherit;border-radius:9px;padding:11px;border:1px solid #334155;background:#0b1220;color:var(--text);max-width:100%}}
button{{cursor:pointer;background:var(--accent);border:0;font-weight:650}}.secondary{{background:#253247}}.danger{{background:#9f3446}}.row{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.grow{{flex:1;min-width:150px}}
small,.muted{{color:var(--muted)}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#060a11;padding:12px;border-radius:10px;max-height:360px;overflow:auto}}
a{{color:#bdb0ff}}.status{{font-size:12px;border:1px solid #334155;padding:4px 8px;border-radius:99px}}
</style></head><body><main><div class="row"><div class="grow"><h1>🚀 BotPilot</h1><div class="sub">Private PHP + Python Telegram Bot Hosting</div></div><span class="status">PRIVATE DASHBOARD</span></div>{body}
<div class="card"><small>Safety note: upload only code you trust. This MVP runs uploaded code inside the same container, not in a strong security sandbox. Render restarts/redeploys can interrupt bots; persistent files are stored on the mounted disk.</small></div></main></body></html>""")

@app.get("/", response_class=HTMLResponse)
def home(user=Depends(auth)):
    meta = read_meta()
    cards = ""
    for bid, b in meta.items():
        status = b.get("status", "unknown")
        cards += f"""<div class="card"><div class="row"><div class="grow"><h3>{b.get('name',bid)}</h3><small>{b.get('entry','')} · ID {bid}</small></div><span class="status">{status.upper()}</span></div>
<p class="muted">Auto-recovery: up to 5 attempts · Restart count: {b.get('restart_count',0)}</p>
<div class="row">
<form method="post" action="/bots/{bid}/start"><button>▶ Start</button></form>
<form method="post" action="/bots/{bid}/stop"><button class="danger">■ Stop</button></form>
<form method="post" action="/bots/{bid}/restart"><button class="secondary">↻ Restart</button></form>
<a href="/bots/{bid}/logs">View logs →</a>
</div></div>"""
    body = f"""<div class="card"><h2>Upload a bot</h2><p class="muted">Upload a ZIP containing bot.php, main.py, bot.py, or another .php/.py entry file in the ZIP root.</p>
<form method="post" action="/upload" enctype="multipart/form-data" class="row">
<input class="grow" name="name" placeholder="Bot name" required>
<input class="grow" type="file" name="file" accept=".zip" required>
<button>Upload ZIP</button></form></div><h2>Your bots ({len(meta)})</h2>{cards or '<div class="card muted">No bots yet. Upload your first ZIP.</div>'}"""
    return page(body)

@app.post("/upload")
async def upload(name: str = Form(...), file: UploadFile = File(...), user=Depends(auth)):
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a ZIP file")
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "ZIP limit is 25 MB")
    bot_id = secrets.token_hex(4)
    dest = bot_dir(bot_id)
    dest.mkdir(parents=True, exist_ok=False)
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            members = z.infolist()
            if len(members) > 500: raise ValueError("Too many files in ZIP")
            for info in members:
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(dest.resolve()) + os.sep) and target != dest.resolve():
                    raise ValueError("Unsafe ZIP path")
                if info.is_dir(): target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, target.open("wb") as out: shutil.copyfileobj(src, out)
        candidates = ["bot.php", "main.php", "bot.py", "main.py"]
        entry = next((x for x in candidates if (dest / x).is_file()), None)
        if not entry:
            candidates_all = sorted([str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and p.suffix in (".php",".py")])
            entry = candidates_all[0] if candidates_all else None
        if not entry: raise ValueError("ZIP must contain at least one .php or .py file")
        meta = read_meta()
        meta[bot_id] = {"id":bot_id,"name":name[:80],"entry":entry,"status":"stopped","desired_state":"stopped","restart_count":0,"uploaded_at":datetime.utcnow().isoformat()+"Z"}
        write_meta(meta)
        append_log(bot_id, f"Uploaded {file.filename}; entry={entry}")
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, f"Upload failed: {e}")
    return RedirectResponse("/", status_code=303)

@app.post("/bots/{bot_id}/start")
def start_route(bot_id: str, user=Depends(auth)):
    meta=read_meta()
    if bot_id not in meta: raise HTTPException(404,"Bot not found")
    meta[bot_id]["desired_state"]="running"; write_meta(meta)
    try: start_bot(bot_id)
    except Exception as e: raise HTTPException(500,str(e))
    return RedirectResponse("/",status_code=303)

@app.post("/bots/{bot_id}/stop")
def stop_route(bot_id: str, user=Depends(auth)):
    meta=read_meta()
    if bot_id not in meta: raise HTTPException(404,"Bot not found")
    meta[bot_id]["desired_state"]="stopped"; write_meta(meta)
    stop_bot(bot_id)
    return RedirectResponse("/",status_code=303)

@app.post("/bots/{bot_id}/restart")
def restart_route(bot_id: str, user=Depends(auth)):
    meta=read_meta()
    if bot_id not in meta: raise HTTPException(404,"Bot not found")
    meta[bot_id]["desired_state"]="running"; write_meta(meta)
    stop_bot(bot_id); start_bot(bot_id)
    return RedirectResponse("/",status_code=303)

@app.get("/bots/{bot_id}/logs", response_class=HTMLResponse)
def logs_route(bot_id: str, user=Depends(auth)):
    meta=read_meta()
    if bot_id not in meta: raise HTTPException(404,"Bot not found")
    try: content=log_path(bot_id).read_text(errors="replace")[-30000:]
    except FileNotFoundError: content="No logs yet."
    import html
    return page(f"""<div class="card"><h2>Logs — {html.escape(meta[bot_id]['name'])}</h2><p><a href="/">← Dashboard</a></p><pre>{html.escape(content)}</pre><form method="post" action="/bots/{bot_id}/clear-logs"><button class="secondary">Clear logs</button></form></div>""","BotPilot Logs")

@app.post("/bots/{bot_id}/clear-logs")
def clear_logs(bot_id: str, user=Depends(auth)):
    if bot_id not in read_meta(): raise HTTPException(404,"Bot not found")
    log_path(bot_id).write_text("")
    return RedirectResponse(f"/bots/{bot_id}/logs",status_code=303)

@app.get("/health")
def health():
    return {"status":"ok"}
