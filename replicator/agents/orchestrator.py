"""Extraction state machine. Steps are stored in the knowledge base, so a run can resume."""
from __future__ import annotations

from replicator.agents import roles
from replicator.agents.disagreement import diff_specs, is_clear_cut
from replicator.agents.runner import RecordingLLM
from replicator.extract.citations import locate, value_present
from replicator.extract.extract import extract_spec
from replicator.extract.llm import LLM, LLMError
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import Citation, F, StrategySpec
from replicator.verify.registry import blocking_issues, citation_rows

PAPER_BUDGET = 24
_OPEN_KINDS = ("escalated", "failed_check", "supervisor")


class Paused(RuntimeError):
    """A usage limit stopped the run. Finished steps are kept."""

    def __init__(self, state: str):
        self.state = state
        super().__init__(
            f"Extraction paused during {state}. Finished steps are saved. "
            "Run extraction again to continue.")


def _get_set(spec: StrategySpec, path: str, other: StrategySpec) -> None:
    """Copy the value for `path` from `other` into `spec`."""
    if path == "chosen_variant_id":
        spec.chosen_variant_id = other.chosen_variant_id
    elif path.startswith("reported_results["):
        key, fld = path[len("reported_results["):].rsplit("].", 1)
        from replicator.agents.disagreement import result_key
        src = next((r for r in other.reported_results if result_key(r) == key), None)
        dst = next((r for r in spec.reported_results if result_key(r) == key), None)
        if src is None:
            return
        if dst is None:
            spec.reported_results.append(src.model_copy(deep=True))
        else:
            setattr(dst, fld, getattr(src, fld))
    else:
        s, o = dict(spec.fields())[path], dict(other.fields())[path]
        s.value, s.status, s.citations, s.note = o.value, o.status, list(o.citations), o.note


def set_value(spec: StrategySpec, path: str, value) -> None:
    """Resolve-with-value helper (UI): set a field/result value directly."""
    if path == "chosen_variant_id":
        spec.chosen_variant_id = str(value)
    elif path.startswith("reported_results["):
        from replicator.agents.disagreement import result_key
        key, fld = path[len("reported_results["):].rsplit("].", 1)
        for r in spec.reported_results:
            if result_key(r) == key:
                setattr(r, fld, value)
    else:
        f: F = dict(spec.fields())[path]
        f.value = value
        f.approved = True


def apply_review_choice(spec: StrategySpec, item: dict, choice) -> StrategySpec:
    """Copy of `spec` with one review decision applied. choice is 'A', 'B', or a literal value."""
    updated = spec.model_copy(deep=True)
    if choice == "A":
        set_value(updated, item["path"], item.get("a_value"))
    elif choice == "B":
        set_value(updated, item["path"], item.get("b_value"))
    else:
        set_value(updated, item["path"], choice)
    return updated


def open_items(kb, paper_id: int) -> list[dict]:
    """Queue rows that still need a person: escalations, failed checks, supervisor notes."""
    return [row for row in kb.list_review_items(paper_id) if row["status"] == "open" and row["kind"] in _OPEN_KINDS]


def _quote_has(value, quote: str) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value_present(float(value), quote)
    from replicator.extract.citations import norm
    return norm(str(value)) in norm(quote)


class Orchestrator:
    """One paper, one mode. States advance in order and never chat with each other."""

    def __init__(self, doc: PaperDocument, llm: LLM, kb, paper_id: int, mode: str = "thorough"):
        self.doc, self.kb, self.paper_id, self.mode = doc, kb, paper_id, mode
        self.recorder = llm if isinstance(llm, RecordingLLM) else RecordingLLM(llm)
        self.llm = self.recorder
        self.trace: list[dict] = []
        self.a: StrategySpec | None = None
        self.b: StrategySpec | None = None
        self.merged: StrategySpec | None = None
        self.diffs: list[dict] = []
        self.items: list[dict] = []
        self.spec_id: int | None = None
        self.check_blob: dict = {}
        self._handlers = {
            "analyst_a": self._analyst_a,
            "analyst_b": self._analyst_b,
            "checks": self._checks,
            "adjudicate": self._adjudicate,
            "revise": self._revise,
            "queue": self._queue,
            "supervisor": self._supervisor,
        }

    def run(self) -> tuple[StrategySpec, list[dict], list[dict]]:
        final = self.kb.trace_get(self.paper_id, f"final_{self.mode}")
        if final is not None:
            return self._from_final(final)
        state = "analyst_a"
        while state != "done":
            self.kb.trace_put(self.paper_id, "cursor", {"state": state, "mode": self.mode})
            state = self._handlers[state]()
        self.kb.trace_put(self.paper_id, "cursor", {"state": "done", "mode": self.mode})
        self._save_log()
        return self.merged, self.items, self.trace

    def _from_final(self, final: dict):
        rows = self.kb.list_review_items(self.paper_id)
        items = [row["item"] | {"id": row["id"], "status": row["status"]}
                 for row in rows if row["kind"] in ("escalated", "auto_settled", "failed_check")]
        self.trace.append({"step": f"final_{self.mode}", "role": "-", "skipped": True,
                           "input_tokens": 0, "output_tokens": 0, "duration_ms": 0})
        return self.kb.get_spec(final["spec_id"]), items, self.trace

    def step(self, name: str, role: str, fn):
        got = self.kb.trace_get(self.paper_id, name)
        if got is not None:
            usage = self.kb.trace_get(self.paper_id, f"usage_{name}") or {}
            self.trace.append({"step": name, "role": role, "skipped": True, **_usage_view(usage)})
            return got
        if len(self.recorder.events) >= PAPER_BUDGET:
            raise Paused(name)
        start = len(self.recorder.events)
        try:
            out = fn()
        except LLMError as exc:
            if _limited(str(exc)):
                raise Paused(name) from exc
            raise
        usage = _sum_usage(self.recorder.events[start:])
        self.kb.trace_put(self.paper_id, name, out)
        self.kb.trace_put(self.paper_id, f"usage_{name}", usage)
        self.trace.append({"step": name, "role": role, "skipped": False, **_usage_view(usage)})
        return out

    def _analyst_a(self) -> str:
        raw = self.step("A", "extract_spec", lambda: extract_spec(self.doc, self.llm).model_dump(mode="json"))
        self.a = StrategySpec.model_validate(raw)
        if self.mode == "economy":
            self.merged = self.a
            self.items = []
            self.spec_id = self.kb.add_spec(self.paper_id, self.a, "extracted", note="economy: single analyst")
            self.kb.trace_put(self.paper_id, "final_economy", {"spec_id": self.spec_id})
            return "done"
        return "analyst_b"

    def _analyst_b(self) -> str:
        raw = self.step("B", "analyst_b", lambda: roles.analyst_b(self.doc, self.llm).model_dump(mode="json"))
        self.b = StrategySpec.model_validate(raw)
        return "checks"

    def _checks(self) -> str:
        def _run() -> dict:
            return {"a": citation_rows(self.a, self.doc), "b": citation_rows(self.b, self.doc)}
        self.check_blob = self.step("checks", "citation_checks", _run)
        return "adjudicate"

    def _adjudicate(self) -> str:
        self.diffs = diff_specs(self.a, self.b)
        batches = [self.diffs[i:i + roles.REVIEW_BATCH] for i in range(0, len(self.diffs), roles.REVIEW_BATCH)]
        batches = batches[:roles.MAX_REVIEW_CALLS]
        decisions: dict[str, dict] = {}
        for i, batch in enumerate(batches):
            got = self.step(f"review_{i}", "spec_reviewer",
                            lambda batch=batch: roles.spec_reviewer(batch, self.doc, self.llm))
            for dec in got:
                decisions[dec.get("path", "")] = dec
        self.merged = self.a.model_copy(deep=True)
        self.items = []
        for diff in self.diffs:
            dec = decisions.get(diff["path"])
            ok, why = is_clear_cut(diff, dec, self.doc)
            item = {**diff, "decision": dec, "reason": why}
            if ok:
                if dec["choice"] == "B":
                    _get_set(self.merged, diff["path"], self.b)
                item.update(kind="auto_settled", reversible=True,
                            evidence={"quote": dec["quote"], "page": dec["page"]})
            else:
                item.update(kind="escalated", reversible=False, evidence=None)
            self.items.append(item)
        return "revise"

    def _revise(self) -> str:
        for n in range(2):
            issues = blocking_issues(self.merged, self.doc)
            if not issues:
                break
            got = self.step(f"revise_{n}", "reviser",
                            lambda issues=issues: roles.reviser(self.merged, issues, self.doc, self.llm))
            patches = got.get("patches") if isinstance(got, dict) else []
            _apply_patches(self.merged, patches or [], self.doc)
        for issue in blocking_issues(self.merged, self.doc):
            self.items.append({
                "path": issue["path"], "a_value": None, "b_value": None, "decision": None,
                "reason": issue["issue"], "kind": "failed_check", "reversible": False, "evidence": None,
            })
        return "queue"

    def _queue(self) -> str:
        note = f"thorough: {len(self.diffs)} disagreements"
        self.spec_id = self.kb.add_spec(self.paper_id, self.merged, "extracted", note=note)
        self.kb.clear_review_items(self.paper_id, ("escalated", "auto_settled", "failed_check"))
        for item in self.items:
            status = "open" if item["kind"] in ("escalated", "failed_check") else "settled"
            item["id"] = self.kb.add_review_item(
                self.paper_id, self.spec_id, item["kind"], item.get("path", ""), item, status)
            item["status"] = status
        return "supervisor"

    def _supervisor(self) -> str:
        rows = []
        for side in ("a", "b"):
            rows.extend(self.check_blob.get(side, []) if isinstance(self.check_blob, dict) else [])

        def _run():
            return roles.supervisor_pass(
                self.merged, rows, self.items,
                {"mode": self.mode, "n_disagreements": len(self.diffs)},
                self.llm, kb=self.kb, paper_id=self.paper_id, spec_id=self.spec_id)

        self.step("supervisor", "supervisor", _run)
        self.kb.trace_put(self.paper_id, "final_thorough", {"spec_id": self.spec_id})
        return "done"

    def _save_log(self) -> None:
        if not self.recorder.events:
            return
        prev = self.kb.trace_get(self.paper_id, "call_log") or []
        self.kb.trace_put(self.paper_id, "call_log", list(prev) + self.recorder.events)


def _apply_patches(spec: StrategySpec, patches: list, doc: PaperDocument) -> None:
    fields = dict(spec.fields())
    for patch in patches:
        if not isinstance(patch, dict):
            continue
        path = str(patch.get("path") or "")
        quote, page = str(patch.get("quote") or ""), int(patch.get("page") or 0)
        found, flag = locate(quote, page, doc)
        if not found or flag or not _quote_has(patch.get("value"), quote):
            continue
        if path not in fields and path != "chosen_variant_id" and not path.startswith("reported_results["):
            continue
        set_value(spec, path, patch.get("value"))
        if path in fields:
            fields[path].citations = [Citation(page=page, quote=quote)]
            fields[path].status = "stated"


def _usage_view(usage: dict) -> dict:
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "duration_ms": int(usage.get("duration_ms") or 0),
    }


def _sum_usage(events: list[dict]) -> dict:
    return {
        "calls": len(events),
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in events),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in events),
        "duration_ms": sum(int(e.get("duration_ms") or 0) for e in events),
        "cache_hit": bool(events) and all(e.get("cache_hit") for e in events),
    }


def _limited(message: str) -> bool:
    text = message.lower()
    return "rate limit" in text or "usage limit" in text or "timed out" in text


def run_extraction(doc: PaperDocument, llm: LLM, kb, paper_id: int, mode: str = "thorough"):
    """Returns (spec, review_items, trace). Finished steps are read back from the KB, not re-called."""
    return Orchestrator(doc, llm, kb, paper_id, mode).run()
