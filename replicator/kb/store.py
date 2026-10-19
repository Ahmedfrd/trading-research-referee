"""SQLite knowledge base. Specs are append-only: an edit is a new version row with parent_id, never an overwrite."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from replicator import config
from replicator.data.provenance import sha256_file
from replicator.kb.manifest import default_export_path, load_manifest, write_manifest
from replicator.spec.model import StrategySpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers(id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, title TEXT, path TEXT, n_pages INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS specs(id INTEGER PRIMARY KEY, paper_id INTEGER, version INTEGER, parent_id INTEGER, source TEXT,
  note TEXT, spec_json TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS code(id INTEGER PRIMARY KEY, spec_id INTEGER, family TEXT, sha256 TEXT, source TEXT,
  bindings_json TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, paper_id INTEGER, spec_id INTEGER, code_id INTEGER, universe TEXT,
  params_json TEXT, summary_json TEXT, artifacts TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS pages(spec_id INTEGER PRIMARY KEY, page_json TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, paper_id INTEGER, text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS review_items(id INTEGER PRIMARY KEY, paper_id INTEGER, spec_id INTEGER, kind TEXT, path TEXT,
  item_json TEXT, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS agent_trace(paper_id INTEGER, step TEXT, output_json TEXT, created TEXT, PRIMARY KEY(paper_id, step));
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(o) -> str:
    return json.dumps(o, default=str)


class KB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.KB_DIR / "kb.sqlite"
        self.root = self.path.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def _q(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()

    def _ins(self, sql: str, args) -> int:
        cur = self.db.execute(sql, args)
        self.db.commit()
        return int(cur.lastrowid)

    # papers
    def add_paper(self, pdf_path, doc=None) -> int:
        sha = sha256_file(pdf_path)
        row = self._q("SELECT id FROM papers WHERE sha256=?", (sha,))
        if row:
            return int(row[0]["id"])
        dest = self.root / "papers" / f"{sha}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf_path, dest)
        title = getattr(doc, "title", "") or Path(pdf_path).stem
        n = len(getattr(doc, "pages", []) or [])
        return self._ins("INSERT INTO papers(sha256,title,path,n_pages,created) VALUES(?,?,?,?,?)",
                         (sha, title, str(dest), n, _now()))

    def list_papers(self) -> pd.DataFrame:
        return pd.DataFrame([dict(r) for r in self._q("SELECT * FROM papers ORDER BY id")])

    # specs
    def add_spec(self, paper_id: int, spec: StrategySpec, source: str, parent_id: int | None = None, note: str = "") -> int:
        v = self._q("SELECT COALESCE(MAX(version),0)+1 AS v FROM specs WHERE paper_id=?", (paper_id,))[0]["v"]
        return self._ins("INSERT INTO specs(paper_id,version,parent_id,source,note,spec_json,created) VALUES(?,?,?,?,?,?,?)",
                         (paper_id, v, parent_id, source, note, spec.model_dump_json(), _now()))

    def get_spec(self, spec_id: int) -> StrategySpec:
        r = self._q("SELECT spec_json FROM specs WHERE id=?", (spec_id,))
        if not r:
            raise KeyError(f"no spec {spec_id}")
        return StrategySpec.model_validate_json(r[0]["spec_json"])

    def list_specs(self, paper_id: int) -> pd.DataFrame:
        return pd.DataFrame([dict(r) for r in self._q(
            "SELECT id,paper_id,version,parent_id,source,note,created FROM specs WHERE paper_id=? ORDER BY version", (paper_id,))])

    def baseline_spec_id(self, paper_id: int) -> int | None:
        r = self._q("SELECT id FROM specs WHERE paper_id=? AND source='approved' ORDER BY version LIMIT 1", (paper_id,))
        return int(r[0]["id"]) if r else None

    def find_spec(self, paper_id: int, spec: StrategySpec) -> int | None:
        js = spec.model_dump_json()
        r = self._q("SELECT id FROM specs WHERE paper_id=? AND spec_json=? ORDER BY version LIMIT 1", (paper_id, js))
        return int(r[0]["id"]) if r else None

    # code
    def add_code(self, spec_id: int, gen) -> int:
        return self._ins("INSERT INTO code(spec_id,family,sha256,source,bindings_json,created) VALUES(?,?,?,?,?,?)",
                         (spec_id, gen.family, gen.sha256, gen.source, _dumps(gen.bindings), _now()))

    def get_code(self, code_id: int):
        from replicator.codegen.render import GeneratedCode
        r = self._q("SELECT * FROM code WHERE id=?", (code_id,))
        if not r:
            raise KeyError(f"no code {code_id}")
        r = r[0]
        return GeneratedCode(r["source"], json.loads(r["bindings_json"]), r["family"], r["sha256"])

    # runs
    def add_run(self, spec_id: int, code_id: int, universe: str, params: dict, summary: dict,
                artifacts: dict[str, pd.DataFrame | pd.Series], manifest: dict | None = None) -> int:
        paper_id = self._q("SELECT paper_id FROM specs WHERE id=?", (spec_id,))[0]["paper_id"]
        run_id = self._ins("INSERT INTO runs(paper_id,spec_id,code_id,universe,params_json,summary_json,artifacts,created) "
                           "VALUES(?,?,?,?,?,?,?,?)",
                           (paper_id, spec_id, code_id, universe, _dumps(params), _dumps(summary), "[]", _now()))
        d = self.root / "runs" / str(run_id)
        d.mkdir(parents=True, exist_ok=True)
        names = []
        for name, obj in artifacts.items():
            df = obj.to_frame(name or "value") if isinstance(obj, pd.Series) else obj
            df = df.copy()
            df.columns = [str(c) for c in df.columns]
            df.to_parquet(d / f"{name}.parquet")
            names.append(name)
        self.db.execute("UPDATE runs SET artifacts=? WHERE id=?", (_dumps(names), run_id))
        self.db.commit()
        if manifest is not None:
            write_manifest(d / "manifest.json", self._stamp_manifest(manifest, run_id, int(paper_id), spec_id, code_id))
        return run_id

    def list_runs(self, paper_id: int | None = None) -> pd.DataFrame:
        sql, args = "SELECT id,paper_id,spec_id,code_id,universe,created FROM runs", ()
        if paper_id is not None:
            sql, args = sql + " WHERE paper_id=?", (paper_id,)
        return pd.DataFrame([dict(r) for r in self._q(sql + " ORDER BY id", args)])

    def get_run(self, run_id: int) -> dict:
        r = self._q("SELECT * FROM runs WHERE id=?", (run_id,))
        if not r:
            raise KeyError(f"no run {run_id}")
        out = dict(r[0])
        out["params"] = json.loads(out.pop("params_json"))
        out["summary"] = json.loads(out.pop("summary_json"))
        names = json.loads(out.pop("artifacts"))
        d = self.root / "runs" / str(run_id)
        out["artifacts"] = {n: pd.read_parquet(d / f"{n}.parquet") for n in names}
        out["manifest"] = self.get_manifest(run_id)
        return out

    def get_manifest(self, run_id: int) -> dict | None:
        path = self.root / "runs" / str(run_id) / "manifest.json"
        return load_manifest(path) if path.is_file() else None

    def export_run(self, run_id: int, dest: Path | None = None) -> Path:
        """Copy the run folder to ``dest`` (default ``reports/exports/run-<id>``) and add spec and code."""
        rows = self._q("SELECT spec_id, code_id FROM runs WHERE id=?", (run_id,))
        if not rows:
            raise KeyError(f"no run {run_id}")
        src = self.root / "runs" / str(run_id)
        if not src.is_dir():
            raise KeyError(f"no artifacts for run {run_id}")
        dest = Path(dest) if dest is not None else default_export_path(run_id)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        (dest / "spec.json").write_text(self.get_spec(int(rows[0]["spec_id"])).model_dump_json(indent=2), encoding="utf-8")
        (dest / "strategy.py").write_text(self.get_code(int(rows[0]["code_id"])).source, encoding="utf-8")
        return dest

    def _stamp_manifest(self, manifest: dict, run_id: int, paper_id: int, spec_id: int, code_id: int) -> dict:
        man = json.loads(json.dumps(manifest))
        man["run_id"] = run_id
        man["paper_id"] = paper_id
        if not man.get("pdf_sha256"):
            paper = self._q("SELECT sha256 FROM papers WHERE id=?", (paper_id,))
            if paper:
                man["pdf_sha256"] = paper[0]["sha256"]
        spec = dict(man.get("spec") or {})
        meta = self._q("SELECT version, source FROM specs WHERE id=?", (spec_id,))
        spec["id"] = spec_id
        if meta:
            spec["version"] = int(meta[0]["version"])
            spec["source"] = meta[0]["source"]
        man["spec"] = spec
        code = dict(man.get("code") or {})
        code["id"] = code_id
        man["code"] = code
        return man

    def count_runs(self, paper_id: int) -> int:
        return int(self._q("SELECT COUNT(*) AS n FROM runs WHERE paper_id=?", (paper_id,))[0]["n"])

    # strategy page, notes
    def save_page(self, spec_id: int, page: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO pages(spec_id,page_json) VALUES(?,?)", (spec_id, _dumps(page)))
        self.db.commit()

    def get_page(self, spec_id: int) -> dict | None:
        r = self._q("SELECT page_json FROM pages WHERE spec_id=?", (spec_id,))
        return json.loads(r[0]["page_json"]) if r else None

    def add_note(self, paper_id: int, text: str) -> int:
        return self._ins("INSERT INTO notes(paper_id,text,created) VALUES(?,?,?)", (paper_id, text, _now()))

    def list_notes(self, paper_id: int) -> pd.DataFrame:
        return pd.DataFrame([dict(r) for r in self._q("SELECT * FROM notes WHERE paper_id=? ORDER BY id", (paper_id,))])

    # agent verification layer
    def add_review_item(self, paper_id: int, spec_id: int | None, kind: str, path: str, item: dict, status: str = "open") -> int:
        return self._ins("INSERT INTO review_items(paper_id,spec_id,kind,path,item_json,status,created) VALUES(?,?,?,?,?,?,?)",
                         (paper_id, spec_id, kind, path, _dumps(item), status, _now()))

    def list_review_items(self, paper_id: int) -> list[dict]:
        return [{**dict(r), "item": json.loads(r["item_json"])} for r in
                self._q("SELECT * FROM review_items WHERE paper_id=? ORDER BY id", (paper_id,))]

    def set_review_status(self, item_id: int, status: str) -> None:
        self._ins("UPDATE review_items SET status=? WHERE id=?", (status, item_id))

    def clear_review_items(self, paper_id: int, kinds: tuple = ()) -> None:
        q, a = "DELETE FROM review_items WHERE paper_id=?", [paper_id]
        if kinds:
            q += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            a += list(kinds)
        self._ins(q, a)

    def trace_put(self, paper_id: int, step: str, output) -> None:
        self._ins("INSERT OR REPLACE INTO agent_trace(paper_id,step,output_json,created) VALUES(?,?,?,?)",
                  (paper_id, step, _dumps(output), _now()))

    def trace_get(self, paper_id: int, step: str):
        r = self._q("SELECT output_json FROM agent_trace WHERE paper_id=? AND step=?", (paper_id, step))
        return json.loads(r[0]["output_json"]) if r else None

    def trace_clear(self, paper_id: int) -> None:
        self._ins("DELETE FROM agent_trace WHERE paper_id=?", (paper_id,))

    def trace_list(self, paper_id: int) -> list[dict]:
        rows = self._q("SELECT step, output_json, created FROM agent_trace WHERE paper_id=? ORDER BY created, step",
                       (paper_id,))
        return [{"step": r["step"], "created": r["created"], "output": json.loads(r["output_json"])} for r in rows]
