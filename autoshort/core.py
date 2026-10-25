from __future__ import annotations
import hashlib, json, os, re, sqlite3, time, tomllib, uuid
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(os.environ.get("AUTOSHORT_ROOT", Path(__file__).resolve().parents[1])).resolve()
DATA = ROOT / "data"
class ReviewNeeded(RuntimeError): pass
class Cancelled(RuntimeError): pass

def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def config():
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8-sig"))

def secret(name):
    if os.environ.get(name): return os.environ[name]
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(name + "="): return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / "autoshort.sqlite", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY, theme TEXT NOT NULL, status TEXT NOT NULL,
      step TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
      error TEXT NOT NULL DEFAULT '', cancel INTEGER NOT NULL DEFAULT 0)""")
    try:
        yield conn
        conn.commit()
    finally: conn.close()

def new_run(theme):
    rid = uuid.uuid4().hex[:16]
    p = DATA / "runs" / rid
    p.mkdir(parents=True)
    dump(p / "config.json", config())
    dump(p / "request.json", {"theme": theme, "created": time.time(), "version": "0.1.0"})
    with db() as conn:
        conn.execute("INSERT INTO runs(id,theme,status,step,created,updated) VALUES(?,?,?,?,?,?)",
                     (rid, theme, "QUEUED", "queued", time.time(), time.time()))
    return rid

def runs():
    with db() as conn: return [dict(x) for x in conn.execute("SELECT * FROM runs ORDER BY created DESC")]

def run_info(rid):
    if not re.fullmatch(r"[a-f0-9]{16}", rid): raise ValueError("Identifiant invalide")
    with db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if row is None: raise ValueError("Production introuvable")
    return dict(row)

def update(rid, **kw):
    if not set(kw) <= {"status", "step", "error", "cancel"}: raise ValueError("Champ interdit")
    kw["updated"] = time.time()
    with db() as conn:
        conn.execute("UPDATE runs SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), rid))

def normalize(text):
    import unicodedata
    s = unicodedata.normalize("NFKD", text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in s if not unicodedata.combining(c))).split())

class Context:
    def __init__(self, rid):
        self.rid = rid
        self.info = run_info(rid)
        self.path = DATA / "runs" / rid
        self.cfg = read(self.path / "config.json")
        self.started = time.monotonic()
        self.usage = read(self.path / "usage.json") if (self.path / "usage.json").exists() else {"llm":0,"search":0,"active_seconds":0}
    def check(self):
        if run_info(self.rid)["cancel"]: raise Cancelled("Arret demande")
        if self.usage.get("active_seconds",0) + time.monotonic()-self.started > self.cfg["production"]["max_run_minutes"]*60:
            raise ReviewNeeded("Budget de temps total atteint")
    def spend(self, kind):
        self.check()
        limit = self.cfg["production"][f"max_{kind}_calls"]
        if self.usage[kind] >= limit: raise ReviewNeeded(f"Budget {kind} atteint")
        self.usage[kind] += 1
        dump(self.path / "usage.json", self.usage)
    def finish_time(self):
        self.usage["active_seconds"] = self.usage.get("active_seconds",0) + time.monotonic()-self.started
        dump(self.path / "usage.json", self.usage)
        self.started = time.monotonic()
    def event(self, stage, message):
        update(self.rid, step=stage)
        with (self.path / "events.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps({"time":time.time(),"stage":stage,"message":message},ensure_ascii=False)+"\n")
    def stage(self, name, fn):
        self.check()
        path = self.path / f"{name}.json"
        if path.exists():
            self.event(name, "Reprise du resultat valide")
            return read(path)
        self.event(name, "En cours")
        result = fn()
        dump(path, result)
        self.event(name, "Termine")
        return result
    def artifact(self, name, value):
        dump(self.path / name, value)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
