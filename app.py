import os, re, json, sqlite3, datetime as dt, urllib.request
from flask import Flask, request, jsonify, g
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE_URL", "sqlite:///liyra.db").replace("sqlite:///", "")
DB = DB if os.path.isabs(DB) else os.path.join(BASE, DB)
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only")
T = {"tasks": "title,description,status,priority,project,due,agent", "memory": "content,type,confidence,status",
     "events": "title,start,end", "approvals": "action,detail,risk,status", "routines": "name,schedule,prompt,agent,enabled",
     "workflows": "name,definition,status", "notifications": "kind,text", "audit": "actor,action,resource,status,risk",
     "documents": "name,content,summary", "agents": "name,description,status,tools,runs,last_action"}
STATUS = ["BACKLOG", "PENDING", "IN_PROGRESS", "BLOCKED", "WAITING_APPROVAL", "DONE"]
INTEG = ["OpenAI", "Claude", "Gemini", "Gmail", "Google Calendar", "GitHub", "Jira", "Slack", "Notion", "Discord", "Trello",
         "Linear", "Outlook", "Google Drive", "Dropbox", "Webhooks"]
ENVKEY = {"OpenAI": "OPENAI_API_KEY", "Claude": "ANTHROPIC_API_KEY", "Gemini": "GOOGLE_AI_API_KEY",
          "Google Calendar": "GOOGLE_CLIENT_ID", "Gmail": "GOOGLE_CLIENT_ID", "GitHub": "GITHUB_CLIENT_ID"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_):
    d = g.pop("db", None); d and d.close()
def q(sql, a=(), one=False):
    c = db().execute(sql, a); db().commit(); r = c.fetchall()
    return (dict(r[0]) if r else None) if one else [dict(x) for x in r]
def now(): return dt.datetime.now().isoformat(timespec="seconds")
def init():
    c = sqlite3.connect(DB)
    for t, cols in T.items():
        c.execute(f"CREATE TABLE IF NOT EXISTS {t}(id INTEGER PRIMARY KEY, {','.join(x+' TEXT' for x in cols.split(','))}, created TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
    c.execute("INSERT OR IGNORE INTO settings VALUES('privacy','GUARDED')")
    if not c.execute("SELECT 1 FROM agents").fetchone():
        for n, d in [("Coding", "Reads/proposes code"), ("Research", "Searches memory & documents"), ("Memory", "Stores/forgets facts"),
                     ("Browser", "Adapter: not configured"), ("Task", "Creates and tracks tasks"), ("System", "Monitors health"),
                     ("Planner", "Breaks goals into tasks"), ("Executive", "Builds briefings")]:
            c.execute("INSERT INTO agents(name,description,status,tools,runs,last_action,created) VALUES(?,?,?,?,0,'-',?)", (n + " Agent", d, "IDLE", "local", now()))
        tm = (dt.date.today() + dt.timedelta(1)).isoformat(); yd = (dt.date.today() - dt.timedelta(1)).isoformat()
        for r in [("Review robotics report", "demo", "PENDING", "HIGH", "demo", tm, "Task Agent"), ("Submit IIC report", "demo", "IN_PROGRESS", "CRITICAL", "demo", yd, "Task Agent"),
                  ("Plan portfolio site", "demo", "BACKLOG", "MEDIUM", "demo", "", "Planner Agent")]:
            c.execute("INSERT INTO tasks(title,description,status,priority,project,due,agent,created) VALUES(?,?,?,?,?,?,?,?)", (*r, now()))
        c.execute("INSERT INTO memory(content,type,confidence,status,created) VALUES('I prefer morning meetings (demo)','Preference','0.9','ACTIVE',?)", (now(),))
        c.execute("INSERT INTO events(title,start,end,created) VALUES('Demo: team sync',?,?,?)", (tm + "T10:00", tm + "T10:30", now()))
        c.execute("INSERT INTO routines(name,schedule,prompt,agent,enabled,created) VALUES('Monday overdue summary (demo)','Mon 09:00','find overdue tasks','Task Agent','1',?)", (now(),))
        c.execute("INSERT INTO workflows(name,definition,status,created) VALUES('Overdue digest (demo)',?,'ACTIVE',?)",
                  (json.dumps(["Trigger:schedule", "Task:find overdue", "AI:summarize", "Approval", "Email:draft"]), now()))
    c.commit(); c.close()

def audit(actor, action, res="", status="OK", risk="LOW"):
    q("INSERT INTO audit(actor,action,resource,status,risk,created) VALUES(?,?,?,?,?,?)", (actor, action, res, status, risk, now()))
def privacy(): return q("SELECT v FROM settings WHERE k='privacy'", one=True)["v"]
def redact(s):
    for p, r in [(r"sk-[A-Za-z0-9_\-]{16,}", "[KEY]"), (r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"), (r"(?i)(password|token|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]")]:
        s = re.sub(p, r, s)
    return s
def ollama(path, data=None):
    req = urllib.request.Request(OLLAMA + path, json.dumps(data).encode() if data else None, {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=4))
def overdue(): return q("SELECT * FROM tasks WHERE due!='' AND due<? AND status NOT IN('DONE','CANCELLED')", (dt.date.today().isoformat(),))
def briefing():
    t = q("SELECT title,priority,due FROM tasks WHERE status NOT IN('DONE','CANCELLED') ORDER BY priority DESC LIMIT 5")
    ev = q("SELECT title,start FROM events WHERE start>=? ORDER BY start LIMIT 5", (dt.date.today().isoformat(),))
    return {"priorities": t, "meetings": ev, "overdue": [x["title"] for x in overdue()], "pending_approvals": len(q("SELECT 1 FROM approvals WHERE status='PENDING'")),
            "active_agents": len(q("SELECT 1 FROM agents WHERE status!='IDLE'")), "privacy": privacy()}

def free_slots(day, mins):
    evs = sorted((e["start"], e["end"]) for e in q("SELECT start,\"end\" AS end FROM events WHERE start LIKE ?", (day + "%",)) if e["start"] and e["end"])
    cur = dt.datetime.fromisoformat(day + "T09:00"); end = dt.datetime.fromisoformat(day + "T18:00"); out = []
    for a, b in evs + [(day + "T18:00", day + "T18:00")]:
        a, b = dt.datetime.fromisoformat(a), dt.datetime.fromisoformat(b)
        if (a - cur).total_seconds() >= mins * 60: out.append(f"{cur:%H:%M}-{a:%H:%M}")
        cur = max(cur, b)
    return out
def conflicts(st, en, skip=0):
    return [e["title"] for e in q("SELECT title,start,\"end\" AS end FROM events") if e["start"] and e["end"] and st < e["end"] and en > e["start"]]
def route(text):
    s = text.strip(); l = s.lower(); steps = ["Understanding request"]
    m = re.match(r"create (?:an? )?(?:(low|medium|high|critical)[- ]priority )?task (?:to )?(.+?)(?: (tomorrow|today))?\.?$", l)
    if m:
        due = {"tomorrow": 1, "today": 0}.get(m.group(3)); due = (dt.date.today() + dt.timedelta(due)).isoformat() if due is not None else ""
        q("INSERT INTO tasks(title,status,priority,due,agent,created) VALUES(?,?,?,?,?,?)", (m.group(2).capitalize(), "PENDING", (m.group(1) or "medium").upper(), due, "Task Agent", now()))
        audit("liyra", "create_task", m.group(2)); return {"reply": f"Created {(m.group(1) or 'medium')}-priority task.", "steps": steps + ["Creating task", "Completed"]}
    m = re.match(r"remember (?:that )?(.+)", l)
    if m:
        q("INSERT INTO memory(content,type,confidence,status,created) VALUES(?,?,?,?,?)", (redact(re.sub(r"(?i)^remember( that)?\s+", "", s)), "Fact", "1.0", "ACTIVE", now()))
        audit("liyra", "store_memory"); return {"reply": "Stored in memory.", "steps": steps + ["Storing memory", "Completed"]}
    m = re.match(r"forget (?:that )?(.+)", l)
    if m:
        words = [w for w in re.findall(r"\w+", m.group(1)) if len(w) > 3]; n = 0
        for r in q("SELECT * FROM memory WHERE status='ACTIVE'"):
            if words and all(w in r["content"].lower() for w in words):
                q("DELETE FROM memory WHERE id=?", (r["id"],)); n += 1
        audit("user", "forget_memory", m.group(1), "OK", "MEDIUM"); return {"reply": f"Forgot {n} memor{'y' if n == 1 else 'ies'}.", "steps": steps + ["Searching memory", "Completed"]}
    m = re.search(r"free (\d+) ?-?(?:minute|min)s? slot(?: (tomorrow|today))?", l)
    if m:
        day = (dt.date.today() + dt.timedelta(1 if m.group(2) != "today" else 0)).isoformat(); return {"reply": f"Free {m.group(1)}-min slots on {day}:", "data": free_slots(day, int(m.group(1))), "steps": steps + ["Checking calendar"]}
    m = re.match(r"search (?:my )?memory for (.+)", l)
    if m: return {"reply": "Keyword search (not vector search):", "data": q("SELECT content,type FROM memory WHERE content LIKE ?", (f"%{m.group(1)}%",)), "steps": steps + ["Searching memory"]}
    if "overdue" in l: return {"reply": f"{len(overdue())} overdue task(s).", "data": overdue(), "steps": steps + ["Checking tasks"]}
    if "task" in l and "show" in l: return {"reply": "Your tasks:", "data": q("SELECT title,status,priority,due FROM tasks"), "steps": steps}
    if "calendar" in l: return {"reply": "Local calendar (Google Calendar: NOT CONNECTED):", "data": q("SELECT title,start FROM events ORDER BY start"), "steps": steps}
    if "briefing" in l: return {"reply": "Executive briefing", "data": briefing(), "steps": steps + ["Checking calendar", "Searching memory", "Preparing briefing", "Completed"]}
    if re.match(r"(send|email)", l):
        q("INSERT INTO approvals(action,detail,risk,status,created) VALUES('send_email',?, 'HIGH','PENDING',?)", (redact(s), now()))
        return {"reply": "Gmail is NOT CONNECTED. Queued for approval; nothing was sent.", "steps": steps + ["Waiting for approval"]}
    try:
        mods = ollama("/api/tags")["models"]; out = ollama("/api/generate", {"model": mods[0]["name"], "prompt": s, "stream": False})
        return {"reply": out["response"], "steps": steps + ["Local model (Ollama)"]}
    except Exception:
        return {"reply": "No LLM connected (OLLAMA OFFLINE). Built-in commands still work.", "steps": steps}

@app.get("/")
def index(): return app.send_static_file("index.html")
@app.errorhandler(Exception)
def err(e):
    app.logger.exception(e); return jsonify(success=False, error="Request failed"), getattr(e, "code", 500)
@app.post("/api/ai/command")
def command():
    t = (request.json or {}).get("text", "").strip()
    if not t: return jsonify(success=False, error="Empty command"), 400
    audit("user", "command", t[:80]); return jsonify(success=True, **route(t))
@app.post("/api/agents/<int:i>/run")
def run_agent(i):
    a = q("SELECT * FROM agents WHERE id=?", (i,), one=True); p = (request.json or {}).get("prompt", "show tasks")
    r = route(p); q("UPDATE agents SET runs=runs+1,status='SUCCESS',last_action=? WHERE id=?", (p[:60], i)); audit(a["name"], "run", p[:60]); return jsonify(success=True, **r)
@app.post("/api/tasks/<int:i>/advance")
def advance(i):
    t = q("SELECT status FROM tasks WHERE id=?", (i,), one=True); n = STATUS[min(STATUS.index(t["status"]) + 1, 5)] if t["status"] in STATUS else "DONE"
    q("UPDATE tasks SET status=? WHERE id=?", (n, i)); audit("user", "advance_task", str(i)); return jsonify(success=True, status=n)
@app.post("/api/approvals/<int:i>/<d>")
def decide(i, d):
    s = {"approve": "APPROVED", "reject": "REJECTED"}.get(d)
    if not s: return jsonify(success=False, error="Bad decision"), 400
    q("UPDATE approvals SET status=? WHERE id=?", (s, i)); audit("user", d, f"approval {i}", "OK", "HIGH")
    return jsonify(success=True, status=s, note="Approved, but external adapter is NOT CONNECTED; nothing executed." if s == "APPROVED" else "")
@app.post("/api/workflows/<int:i>/run")
def run_wf(i):
    w = q("SELECT * FROM workflows WHERE id=?", (i,), one=True); log = []
    for n in json.loads(w["definition"]):
        if n.startswith(("Email", "Approval")):
            q("INSERT INTO approvals(action,detail,risk,status,created) VALUES(?,?,?,?,?)", (f"workflow:{w['name']}", n, "HIGH", "PENDING", now())); log.append(n + " -> waiting approval"); break
        log.append(n + " -> done")
    audit("workflow", "run", w["name"]); return jsonify(success=True, log=log)
@app.get("/api/integrations")
def integ():
    ol = "OFFLINE"
    try: ollama("/api/tags"); ol = "CONNECTED"
    except Exception: pass
    return jsonify(success=True, data=[{"name": n, "status": ol if n == "Ollama" else ("CONFIGURED (key present, untested)" if os.environ.get(ENVKEY.get(n, "_")) else "NOT CONNECTED")} for n in ["Ollama"] + INTEG])
@app.get("/api/security")
def sec(): return jsonify(success=True, privacy=privacy(), encryption_key="SET" if os.environ.get("ENCRYPTION_KEY") else "MISSING - configure ENCRYPTION_KEY", secret_key="SET" if os.environ.get("SECRET_KEY") else "DEV DEFAULT")
@app.post("/api/settings/privacy")
def setpriv():
    m = (request.json or {}).get("mode", "")
    if m not in ("STRICT", "GUARDED", "RELAXED"): return jsonify(success=False, error="Invalid mode"), 400
    q("UPDATE settings SET v=? WHERE k='privacy'", (m,)); audit("user", "privacy_mode", m, "OK", "MEDIUM"); return jsonify(success=True, mode=m)
@app.get("/api/system")
def system():
    try:
        import psutil; return jsonify(success=True, cpu=psutil.cpu_percent(), ram=psutil.virtual_memory().percent, disk=psutil.disk_usage("/").percent)
    except ImportError: return jsonify(success=True, cpu="UNAVAILABLE", ram="UNAVAILABLE", disk="UNAVAILABLE")
@app.get("/api/search")
def search():
    k = f"%{request.args.get('q', '')}%"
    return jsonify(success=True, data={t: q(f"SELECT id,{c.split(',')[0]} AS label FROM {t} WHERE {c.split(',')[0]} LIKE ?", (k,)) for t, c in [("tasks", T["tasks"]), ("memory", T["memory"]), ("documents", T["documents"])]})
@app.get("/api/analytics")
def analytics():
    c = lambda s: q(s, one=True)["n"]
    return jsonify(success=True, tasks_done=c("SELECT COUNT(*) n FROM tasks WHERE status='DONE'"), agent_runs=c("SELECT COALESCE(SUM(runs),0) n FROM agents"), commands=c("SELECT COUNT(*) n FROM audit WHERE action='command'"), llm_tokens="UNAVAILABLE (no provider connected)")
@app.get("/api/briefing")
def brief(): return jsonify(success=True, data=briefing())
@app.get("/api/<t>")
def lst(t):
    if t not in T: return jsonify(success=False, error="Unknown resource"), 404
    return jsonify(success=True, data=q(f"SELECT * FROM {t} ORDER BY id DESC"))
@app.post("/api/<t>")
def add(t):
    if t not in T: return jsonify(success=False, error="Unknown resource"), 404
    d = request.json or {}; cols = T[t].split(",")
    if not any(str(d.get(c, "")).strip() for c in cols[:1]): return jsonify(success=False, error=f"{cols[0]} is required"), 400
    warn = conflicts(d.get("start", ""), d.get("end", "")) if t == "events" else []
    if t == "documents": d["summary"] = (d.get("content", "")[:200] if d.get("name", "").lower().endswith((".txt", ".md", ".json", ".csv")) or "." not in d.get("name", "") else "parser unavailable for this file type")
    q(f"INSERT INTO {t}({','.join(cols)},created) VALUES({','.join('?' * (len(cols) + 1))})", (*[str(d.get(c, "")) for c in cols], now())); audit("user", "create", t)
    return jsonify(success=True, warning=("Conflicts with: " + ", ".join(warn)) if warn else "")
@app.patch("/api/<t>/<int:i>")
def upd(t, i):
    if t not in T: return jsonify(success=False, error="Unknown resource"), 404
    for k, v in (request.json or {}).items():
        if k in T[t].split(","): q(f"UPDATE {t} SET {k}=? WHERE id=?", (str(v), i))
    return jsonify(success=True)
@app.delete("/api/<t>/<int:i>")
def rm(t, i):
    if t not in T: return jsonify(success=False, error="Unknown resource"), 404
    q(f"DELETE FROM {t} WHERE id=?", (i,)); audit("user", "delete", f"{t}/{i}", "OK", "MEDIUM"); return jsonify(success=True)
init()
if __name__ == "__main__": app.run(debug=False, port=5000)
