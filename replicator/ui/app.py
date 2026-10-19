"""Streamlit app for the replicator. Run: streamlit run replicator/ui/app.py"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from replicator.ui.errors import user_message

ROOT = Path(__file__).resolve().parents[2]
PAPERS_DIR = ROOT / "data" / "papers"
GOLDEN = ["jt", "tsmom", "umd", "kmz"]

st.set_page_config(page_title="Replicator", layout="wide")

_missing: dict[str, str] = {}


def _try(name: str, fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        _missing[name] = f"{type(e).__name__}: {e}"
        return None


KBc = _try("kb", lambda: __import__("replicator.kb.store", fromlist=["KB"]).KB)
codegen = _try("codegen", lambda: __import__("replicator.codegen.render", fromlist=["render"]))
pipeline = _try("pipeline", lambda: __import__("replicator.pipeline", fromlist=["run"]))
model = _try("spec", lambda: __import__("replicator.spec.model", fromlist=["StrategySpec"]))
pdfmod = _try("ingest", lambda: __import__("replicator.ingest.pdf", fromlist=["load_pdf"]))
llmmod = _try("llm", lambda: __import__("replicator.extract.llm", fromlist=["ClaudeCLI"]))
extmod = _try("extract", lambda: __import__("replicator.extract.extract", fromlist=["extract_spec"]))
citmod = _try("citations", lambda: __import__("replicator.extract.citations", fromlist=["verify_citations"]))
expmod = _try("explain", lambda: __import__("replicator.extract.explain", fromlist=["strategy_page"]))


def unavailable(name: str) -> bool:
    if name in _missing or _try_get(name) is None:
        st.info(f"Module not available yet: {name}")
        return True
    return False


def _try_get(name: str):
    return {"kb": KBc, "codegen": codegen, "pipeline": pipeline, "spec": model, "ingest": pdfmod,
            "llm": llmmod, "extract": extmod, "citations": citmod, "explain": expmod}.get(name)


def err(e: Exception) -> None:
    msg = user_message(e)
    if type(e).__name__ == "Unsupported":
        st.warning(msg)
    else:
        st.error(msg)


def get_kb():
    if KBc is None:
        return None
    if "kb" not in st.session_state:
        try:
            st.session_state["kb"] = KBc()
        except Exception as e:  # noqa: BLE001
            err(e)
            return None
    return st.session_state["kb"]


def safe_df(fn, *a) -> pd.DataFrame:
    try:
        d = fn(*a)
        return d if isinstance(d, pd.DataFrame) else pd.DataFrame()
    except Exception as e:  # noqa: BLE001
        err(e)
        return pd.DataFrame()


def show_df(df: pd.DataFrame, **kw) -> None:
    if df is None or len(df) == 0:
        st.caption("Nothing here yet.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True, **kw)


STATUS_COL = {"stated": "#d4edda", "derived": "#e2eafc", "assumed": "#fff3cd", "unknown": "#f8d7da",
              "pass": "#d4edda", "fail": "#f8d7da", "warn": "#fff3cd", "n/a": "#e9ecef",
              "replicated": "#d4edda", "not replicated": "#f8d7da", "not comparable": "#e9ecef"}


def colour_status(df: pd.DataFrame, col: str = "status"):
    if col not in df.columns:
        return df
    return df.style.map(lambda v: f"background-color: {STATUS_COL.get(str(v).lower(), '')}", subset=[col])


# ---------------------------------------------------------------- sidebar
kb = get_kb()
papers = safe_df(kb.list_papers) if kb else pd.DataFrame()
st.sidebar.title("Replicator")
if _missing:
    st.sidebar.warning("Not available yet: " + ", ".join(sorted(_missing)))
paper_id = None
paper_row: dict = {}
if len(papers):
    idcol = "id" if "id" in papers.columns else papers.columns[0]
    labels = {}
    for _, r in papers.iterrows():
        t = r.get("title") if "title" in papers.columns else None
        labels[int(r[idcol])] = f"{int(r[idcol])}: {t or r.get('sha256', '')[:10]}"
    paper_id = st.sidebar.selectbox("Paper", list(labels), format_func=labels.get)
    paper_row = papers[papers[idcol] == paper_id].iloc[0].to_dict()
else:
    st.sidebar.caption("No papers yet. Upload a PDF on the Library tab.")
st.sidebar.caption("Library → Paper & spec → Review queue → Code → Results")
model_name = st.sidebar.selectbox("Model", ["sonnet", "opus", "haiku"], index=0)
extract_label = st.sidebar.radio(
    "Extraction",
    ["Thorough", "Single analyst"],
    index=0,
    help="Thorough is the default: two analysts, a reviewer, and one supervisor pass. "
         "Single analyst is the shorter path.",
)
extract_mode = "thorough" if extract_label == "Thorough" else "economy"
_ROLE_MODELS = (
    ("extract_spec", "Analyst A"), ("analyst_b", "Analyst B"), ("spec_reviewer", "Spec reviewer"),
    ("reviser", "Reviser"), ("supervisor", "Supervisor"), ("strategy_page", "Strategy page"),
    ("fact_checker", "Fact-checker"), ("results_analyst", "Results note"),
)
_MODELS = ["sonnet", "opus", "haiku"]
role_models: dict[str, str] = {}
with st.sidebar.expander("Model per role"):
    st.caption("Each role uses its own model. A new session starts them on the model selected above.")
    for key, title in _ROLE_MODELS:
        role_models[key] = st.selectbox(title, _MODELS, index=_MODELS.index(model_name), key=f"role_model_{key}")
with st.sidebar.expander("What a thorough run does"):
    st.caption("Analyst A and analyst B read the paper separately. A field-level diff is code. "
               "The spec reviewer may settle a disagreement only when the quote check passes. "
               "Anything else, and every assumption, waits for you. "
               "The supervisor adds notes and cannot change the spec. "
               "Code is a template. A model does not write strategy code, and it does not compute results.")


def pdf_file() -> Path | None:
    if not paper_row:
        return None
    sha = paper_row.get("sha256", "")
    for c in [paper_row.get("path"), paper_row.get("pdf_path"), ROOT / "data" / "kb" / "papers" / f"{sha}.pdf"]:
        if c and Path(str(c)).exists():
            return Path(str(c))
    return None


def load_doc():
    if pdfmod is None:
        return None
    path = pdf_file()
    return pdfmod.load_pdf(path) if path is not None else None


def make_runner():
    from replicator.agents.runner import Runner
    return Runner(model=model_name, models=role_models)


def ingest_upload(upload) -> None:
    if kb is None or pdfmod is None:
        st.info("The knowledge base is not available, so the PDF was not stored.")
        return
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PAPERS_DIR / upload.name
    dest.write_bytes(upload.getvalue())
    with st.spinner("Reading PDF"):
        doc = pdfmod.load_pdf(dest)
        pid = kb.add_paper(dest, doc)
    st.success(f"Paper stored as id {pid}. Select it in the sidebar.")


def approval_blockers(s) -> list[str]:
    """Spec fields the paper did not state that you have not yet approved. Code generation waits on these."""
    if s is None:
        return []
    try:
        return [p for p, f in s.fields() if f.status in ("assumed", "unknown") and not f.approved]
    except Exception:  # noqa: BLE001
        return []


def open_queue() -> list:
    if kb is None or paper_id is None:
        return []
    try:
        from replicator.agents.orchestrator import open_items
        return open_items(kb, paper_id)
    except Exception:  # noqa: BLE001
        return []


def gate(s) -> bool:
    """True when assumptions are approved and the review queue has nothing open."""
    waiting = open_queue()
    if waiting:
        st.warning(f"Code generation is blocked: {len(waiting)} open item(s) in the Review queue. "
                   "Approve or reject them first. Code is generated only after that, and only from an approved spec.")
        return False
    blockers = approval_blockers(s)
    if blockers:
        st.warning(f"Code generation is blocked: {len(blockers)} assumed or unknown field(s) are not yet approved "
                   "(Paper & spec tab). Code is generated only from an approved spec.")
        st.caption(", ".join(blockers[:12]) + (" …" if len(blockers) > 12 else ""))
        return False
    return True


def current_spec_id(prefer_approved: bool = True):
    """Selected spec version for the sidebar paper."""
    if kb is None or paper_id is None:
        return None
    specs = safe_df(kb.list_specs, paper_id)
    if specs.empty:
        return None
    idc = "id" if "id" in specs.columns else specs.columns[0]
    ids = [int(x) for x in specs[idc]]
    pick = st.sidebar.selectbox("Spec version", ids, index=len(ids) - 1,
                                format_func=lambda i: f"spec #{i}" + (" (baseline)" if i == _baseline() else ""))
    return pick


def _baseline():
    try:
        return kb.baseline_spec_id(paper_id)
    except Exception:  # noqa: BLE001
        return None


spec_id = current_spec_id()
spec = None
if spec_id is not None:
    try:
        spec = kb.get_spec(spec_id)
    except Exception as e:  # noqa: BLE001
        err(e)

tabs = st.tabs(["Library", "Paper & spec", "Strategy page", "Code", "Results", "Variables", "Golden set",
                "Supervisor", "Review queue"])


def fget(s, path):
    o = s
    for p in path.split("."):
        o = getattr(o, p)
    return o


# ---------------------------------------------------------------- 1 Library
with tabs[0]:
    st.subheader("Library")
    st.caption("Upload a paper, then select it in the sidebar. The next step is Paper & spec.")
    up = st.file_uploader("Upload a paper (PDF)", type=["pdf"])
    ready = up is not None and kb is not None and pdfmod is not None
    if not ready:
        st.caption("Choose a PDF, then add it to the library.")
    if st.button("Add to library", disabled=not ready):
        try:
            ingest_upload(up)
        except Exception as e:  # noqa: BLE001
            err(e)
    if kb is None:
        st.info("The knowledge base is not available.")
    elif papers.empty:
        st.info("No papers yet. Upload a PDF to start.")
    st.subheader("Papers")
    show_df(papers)
    if kb and paper_id is not None:
        st.subheader("Spec versions")
        show_df(safe_df(kb.list_specs, paper_id))
        st.subheader("Runs")
        show_df(safe_df(kb.list_runs, paper_id))
        st.subheader("Notes")
        try:
            notes = kb.list_notes(paper_id)
            if isinstance(notes, pd.DataFrame):
                show_df(notes)
            else:
                for n in notes or []:
                    st.write("- " + str(n))
        except Exception as e:  # noqa: BLE001
            err(e)
        txt = st.text_area("New note", key="note_txt")
        if st.button("Add note") and txt.strip():
            try:
                kb.add_note(paper_id, txt.strip())
                st.success("Note saved.")
            except Exception as e:  # noqa: BLE001
                err(e)

# ---------------------------------------------------------------- 2 Paper & spec
with tabs[1]:
    st.subheader("Paper & spec")
    run_label = "Run thorough extraction" if extract_mode == "thorough" else "Run single-analyst extraction"
    if paper_id is None:
        st.info("Select a paper in the sidebar, or upload a PDF on the Library tab.")
        st.button(run_label, disabled=True)
    else:
        has_pdf = pdf_file() is not None
        st.caption("Thorough runs analyst A, analyst B, the spec reviewer, and one supervisor pass. "
                   "Single analyst runs one extraction. Choose the mode in the sidebar. "
                   "Open disagreements go to the Review queue. Approve assumptions here before Code.")
        try:
            from replicator.agents.runner import claude_on_path
            if not claude_on_path():
                st.caption("Claude CLI is not on PATH. A cached or fixture result is used when one exists. "
                           "Otherwise extraction stops immediately and does not wait on a live model.")
        except Exception:  # noqa: BLE001
            pass
        if not has_pdf:
            st.caption("The PDF for this paper is not on disk, so extraction is unavailable.")
        if st.button(run_label, disabled=not has_pdf or kb is None):
            try:
                from replicator.agents.orchestrator import run_extraction
                doc = load_doc()
                if doc is None:
                    raise FileNotFoundError("PDF for this paper not found")
                with st.spinner("Reading the paper. Finished steps are kept if this pauses."):
                    _spec, items, trace = run_extraction(doc, make_runner(), kb, paper_id, extract_mode)
                open_n = sum(1 for it in items if it.get("status") == "open")
                if open_n:
                    st.success(f"Extraction finished with {open_n} item(s) in the Review queue.")
                else:
                    st.success("Extraction finished. Review auto-settled fields, then approve assumptions.")
                st.caption(f"{sum(1 for t in trace if not t.get('skipped'))} new step(s); "
                           f"{sum(1 for t in trace if t.get('skipped'))} reused.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "Paused":
                    st.warning(user_message(e))
                else:
                    err(e)
        if spec is None:
            st.info("No spec for this paper yet.")
        else:
            doc = None
            checks = []
            try:
                doc = load_doc()
                if doc is not None and citmod is not None:
                    checks = citmod.verify_citations(spec, doc)
            except Exception as e:  # noqa: BLE001
                err(e)
            cmap: dict[tuple[str, int, str], str] = {}

            def verdict(c) -> str:
                if c.found_on_page and not c.issue:
                    return "verified"
                if "adjacent" in c.issue or "another page" in c.issue:
                    return "wrong page"
                if "not found" in c.issue or "no quote" in c.issue:
                    return "NOT FOUND"
                if c.value_in_quote is False:
                    return "value not in quote"
                return c.issue or "NOT FOUND"

            for c in checks:
                v = verdict(c)
                if c.value_in_quote is False and v == "verified":
                    v = "value not in quote"
                cmap[(c.path, c.page, c.quote)] = v
            rows = []
            for path, f in spec.fields():
                cits = "; ".join(f"p.{c.page}: {c.quote[:120]}" for c in f.citations)
                cv = ", ".join(sorted({cmap.get((path, c.page, c.quote), "not checked") for c in f.citations}))
                rows.append({"field": path, "value": json.dumps(f.value, default=str), "status": f.status,
                             "citations": cits, "citation check": cv or ("no citation" if f.status in
                                                                         ("stated", "derived") else "")})
            st.markdown(f"**Family:** {spec.family}   **Chosen variant:** {spec.chosen_variant_id or '-'}")
            st.dataframe(colour_status(pd.DataFrame(rows)), use_container_width=True, hide_index=True)
            st.subheader("Reported results")
            if spec.reported_results:
                vids = {v.id for v in spec.variants}
                rr = pd.DataFrame([r.model_dump() for r in spec.reported_results])
                rr.insert(2, "is_variant", rr["variant_id"].map(lambda v: bool(v) and v != spec.chosen_variant_id))
                st.dataframe(rr, use_container_width=True, hide_index=True)
            else:
                st.caption("No reported results extracted.")
            with st.expander("Raw JSON"):
                st.json(json.loads(spec.model_dump_json()))
            st.subheader("Assumptions")
            ass = spec.assumptions()
            if not ass:
                st.success("No assumed or unknown fields.")
            edits, approvals = {}, {}
            for path, f in ass:
                a, b, c = st.columns([3, 3, 1])
                a.markdown(f"`{path}`  \n{f.status}: {f.note or ''}")
                edits[path] = b.text_input("value", value=json.dumps(f.value, default=str),
                                           key=f"ed_{spec_id}_{path}", label_visibility="collapsed")
                approvals[path] = c.checkbox("Approve", value=bool(f.approved), key=f"ap_{spec_id}_{path}")
            all_ok = all(approvals.values()) if ass else True
            waiting = open_queue()
            if waiting:
                st.warning(f"{len(waiting)} open item(s) are in the Review queue. Approve or reject them before approving the spec.")
            elif not all_ok:
                st.warning("Code generation is disabled until every assumed or unknown field is approved.")
            if st.button("Approve spec", disabled=not all_ok or bool(waiting)):
                try:
                    from datetime import datetime, timezone
                    new = spec.model_copy(deep=True)
                    for path, _ in ass:
                        f = fget(new, path)
                        try:
                            f.value = json.loads(edits[path])
                        except Exception:  # noqa: BLE001
                            f.value = edits[path]
                        f.approved = True
                    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    sid = kb.add_spec(paper_id, new, "approved", parent_id=spec_id, note=f"approved {stamp}")
                    st.success(f"Approved spec saved as #{sid}.")
                except Exception as e:  # noqa: BLE001
                    err(e)

# ---------------------------------------------------------------- 3 Strategy page
with tabs[2]:
    st.subheader("Strategy page")
    if spec is None:
        st.info("Select a paper with a spec. Extract it on Paper & spec first.")
    else:
        page = None
        try:
            page = kb.get_page(spec_id)
        except Exception as e:  # noqa: BLE001
            err(e)
        has_pdf = pdf_file() is not None
        if not has_pdf:
            st.caption("The PDF is not on disk, so a new page cannot be written.")
        if st.button("Generate strategy page", disabled=not has_pdf):
            if _try_get("explain") is None or _try_get("llm") is None:
                st.info("The strategy-page writer is not available.")
            else:
                try:
                    from replicator.agents.roles import fact_check
                    doc = load_doc()
                    if doc is None:
                        raise FileNotFoundError("PDF for this paper not found")
                    runner = make_runner()
                    with st.spinner("Writing the strategy page"):
                        page = expmod.strategy_page(spec, doc, runner)
                        if extract_mode == "thorough":
                            try:
                                page["fact_check"] = fact_check(page, doc, runner)
                            except Exception as e:  # noqa: BLE001
                                page["fact_check_error"] = user_message(e)
                        kb.save_page(spec_id, page)
                except Exception as e:  # noqa: BLE001
                    err(e)
        if not page:
            st.info("No strategy page for this spec yet.")
        else:
            verdicts = {(v.get("heading"), v.get("index")): v
                        for v in (page.get("fact_check") or {}).get("verdicts", [])}
            if page.get("fact_check_error"):
                st.warning(page["fact_check_error"])
            for sec in page.get("sections", []):
                st.markdown(f"### {sec.get('heading', '')}")
                for i, p in enumerate(sec.get("paragraphs", [])):
                    if p.get("kind") == "referee_note":
                        st.info("Referee note: " + p.get("text", ""))
                        continue
                    chips = " ".join(
                        f"`[p.{c.get('page')}] {'on page' if c.get('found') and not c.get('flag') else 'not on page'}`"
                        for c in p.get("citations", []))
                    st.markdown(p.get("text", "") + ("  \n" + chips if chips else "  \n`no citation`"))
                    hit = verdicts.get((sec.get("heading"), i))
                    if hit:
                        st.caption(("Quote supports this sentence." if hit.get("supports") else "Quote does not support this sentence.")
                                   + (f" {hit.get('note')}" if hit.get("note") else ""))

# ---------------------------------------------------------------- 4 Code
gen = None
with tabs[3]:
    st.subheader("Code")
    if spec is None:
        st.info("Select a paper with a spec, then approve it on Paper & spec.")
    elif unavailable("codegen"):
        pass
    elif not gate(spec):
        pass
    else:
        try:
            from replicator.agents.code_roles import family_message, review_code, test_plan
            st.caption(family_message(spec))
            gen = codegen.render(spec)
            st.caption(f"Family: {gen.family}   sha256: {gen.sha256[:12]}")
            st.code(gen.source, language="python")
            b = pd.DataFrame([{"constant": v.get("name"), "spec path": k, "value": json.dumps(v.get("value"), default=str),
                               "status": ""} for k, v in gen.bindings.items()])
            try:
                stat = dict(spec.fields())
                b["status"] = [stat[k].status if k in stat else "" for k in gen.bindings]
            except Exception:  # noqa: BLE001
                pass
            st.dataframe(colour_status(b), use_container_width=True, hide_index=True)
            findings = review_code(gen, spec)
            if findings:
                for item in findings:
                    st.error(item["issue"])
            else:
                st.success("The template checks passed: every binding is used, and no unbound number remains.")
            st.markdown("**Checks that run with the strategy**")
            for line in test_plan(spec):
                st.caption(line)
        except Exception as e:  # noqa: BLE001
            err(e)

# ---------------------------------------------------------------- 5 Results
def show_outcome(out) -> None:
    st.markdown(f"### Replication level: `{out.replication_level}`")
    st.caption(f"Family {out.family}; universe {out.universe}")
    st.subheader("Disclosures")
    for d in out.disclosures:
        st.warning(d)
    st.subheader("Paper vs ours")
    st.dataframe(colour_status(out.comparison), use_container_width=True, hide_index=True)
    reasons = getattr(out, "gap_reasons", None) or []
    if reasons:
        st.subheader("Likely reasons for any gap")
        st.caption("Computed from this run's own data and the spec, not written by a model. "
                   "'Quantified' is filled in only where it was measured.")
        st.dataframe(pd.DataFrame(reasons), use_container_width=True, hide_index=True)
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        for nm, res in (("Strategy", out.strategy), ("Benchmark", out.benchmark)):
            eq = (1 + res.returns.dropna()).cumprod()
            fig.add_scatter(x=eq.index, y=eq.values, name=nm)
        fig.update_yaxes(type="log", title="Growth of 1")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:  # noqa: BLE001
        err(e)
    a, b = st.columns(2)
    a.markdown("**Strategy stats**")
    a.dataframe(pd.Series(out.stats, name="strategy").astype(str), use_container_width=True)
    b.markdown("**Benchmark stats**")
    b.dataframe(pd.Series(out.bench_stats, name="benchmark").astype(str), use_container_width=True)
    st.subheader("The six checks")
    for c in out.checks:
        icon = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "n/a": "N/A"}.get(c.status, c.status)
        with st.expander(f"[{icon}] {c.name}: {c.headline}"):
            st.caption(c.method)
            st.json(json.loads(json.dumps(c.details, default=str)))
            if c.cross_check:
                st.markdown("Cross-check")
                st.json(json.loads(json.dumps(c.cross_check, default=str)))


with tabs[4]:
    st.subheader("Results")
    if spec is None:
        st.info("Select a paper with an approved spec. Run it here after Code.")
        st.button("Run", disabled=True)
    elif unavailable("pipeline"):
        pass
    elif not gate(spec):
        pass
    else:
        try:
            alts = pipeline.alternative_universes(spec)
        except Exception as e:  # noqa: BLE001
            err(e)
            alts = []
        feas = [a for a in alts if a.get("feasible")]
        for a in alts:
            if not a.get("feasible"):
                st.caption(f"Unavailable: {a.get('label', a.get('key'))} — {a.get('reason', '')}")
        if not feas:
            st.info("No feasible universe for this spec, so Run is disabled.")
        ukey = st.selectbox("Universe", [a["key"] for a in feas], key="res_u",
                            format_func=lambda k: next(a["label"] for a in feas if a["key"] == k)) if feas else None
        try:
            dc = float(spec.execution.cost_bps.value or 0.0)
        except Exception:  # noqa: BLE001
            dc = 0.0
        cost = st.number_input("Cost (bps, one-way)", value=dc, min_value=0.0, step=5.0, key="res_c")
        if st.button("Run", disabled=not feas):
            try:
                with st.spinner("Running pipeline"):
                    st.session_state["outcome"] = pipeline.run(
                        spec, universe_key=ukey, cost_bps=cost, kb=kb, paper_id=paper_id, spec_id=spec_id)
            except Exception as e:  # noqa: BLE001
                err(e)
        outcome = st.session_state.get("outcome")
        if outcome is not None:
            try:
                show_outcome(outcome)
                man = getattr(outcome, "manifest", None) or {}
                if man.get("run_id"):
                    st.caption(f"Run {man['run_id']} wrote a manifest and an export folder.")
            except Exception as e:  # noqa: BLE001
                err(e)
            if st.button("Draft gap note", disabled=outcome is None):
                try:
                    from replicator.agents.roles import results_note
                    note = results_note(
                        outcome.comparison.to_dict("records"), list(outcome.gap_reasons or []),
                        outcome.stats, make_runner())
                    if note["issues"]:
                        st.warning("The draft quoted " + ", ".join(note["issues"])
                                   + ", which is not in the computed table, so the draft was withheld.")
                    elif note["text"]:
                        st.info(note["text"])
                    else:
                        st.caption("The draft was empty. The table above is the result.")
                except Exception as e:  # noqa: BLE001
                    err(e)

# ---------------------------------------------------------------- 6 Variables
with tabs[5]:
    if spec is None:
        st.info("Select a paper with a spec.")
    elif unavailable("pipeline"):
        pass
    elif not gate(spec):
        pass
    else:
        st.caption("Baseline values are locked. Each variant you run counts toward the multiple-testing bar.")
        base = _baseline()
        bspec = None
        try:
            bspec = kb.get_spec(base) if base else None
        except Exception:  # noqa: BLE001
            pass
        ov = {}
        for sec in ("params", "execution"):
            for k, f in getattr(spec, sec):
                path = f"{sec}.{k}"
                bv = fget(bspec, path).value if bspec else f.value
                a, b, c = st.columns([2, 2, 3])
                a.markdown(f"`{path}`")
                b.text_input("baseline (locked)", value=json.dumps(bv, default=str), disabled=True,
                             key=f"bl_{path}", label_visibility="collapsed")
                nv = c.text_input("value", value=json.dumps(f.value, default=str), key=f"ov_{path}",
                                  label_visibility="collapsed")
                try:
                    val = json.loads(nv)
                except Exception:  # noqa: BLE001
                    val = nv
                if val != bv:
                    ov[path] = val
        try:
            alts = [a for a in pipeline.alternative_universes(spec) if a.get("feasible")]
        except Exception:  # noqa: BLE001
            alts = []
        vu = st.selectbox("Universe", [a["key"] for a in alts], key="var_u") if alts else None
        vc = st.number_input("Cost (bps)", value=0.0, min_value=0.0, key="var_c")
        if st.button("Re-run with overrides"):
            try:
                n = kb.count_runs(paper_id) + 1 if kb else 1
                with st.spinner("Running variant"):
                    st.session_state["var_out"] = pipeline.run(spec, universe_key=vu, overrides=ov or None,
                                                               cost_bps=vc or None, n_trials=n, kb=kb,
                                                               paper_id=paper_id)
            except Exception as e:  # noqa: BLE001
                err(e)
        vo = st.session_state.get("var_out")
        if vo is not None:
            try:
                st.subheader("Diff vs baseline")
                st.json(json.loads(json.dumps(vo.diff_vs_baseline, default=str)))
                show_outcome(vo)
            except Exception as e:  # noqa: BLE001
                err(e)
        st.subheader("Runs for this paper")
        show_df(safe_df(kb.list_runs, paper_id))

# ---------------------------------------------------------------- 7 Golden set
with tabs[6]:
    for key in GOLDEN:
        st.subheader(key.upper())
        p = ROOT / "reports" / "golden" / f"{key}.json"
        if not p.exists():
            st.caption("not yet generated")
            continue
        try:
            g = json.loads(p.read_text())
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not read {p.name}: {e}")
            continue
        st.markdown(f"Replication level: `{g.get('replication_level', '?')}`")
        comp = g.get("comparison")
        if comp:
            try:
                st.dataframe(colour_status(pd.DataFrame(comp)), use_container_width=True, hide_index=True)
            except Exception:  # noqa: BLE001
                st.json(comp)
        for d in g.get("disclosures", []) or []:
            st.warning(str(d))
        if g.get("notes"):
            n = g["notes"]
            st.markdown("\n".join(f"- {x}" for x in n) if isinstance(n, list) else str(n))
        with st.expander("Raw JSON"):
            st.json(g)

def _step_label(step: str) -> str:
    names = {"A": "Analyst A", "B": "Analyst B", "checks": "Citation checks", "supervisor": "Supervisor"}
    if step in names:
        return names[step]
    if step.startswith("review_"):
        return "Spec reviewer"
    if step.startswith("revise_"):
        return "Reviser"
    return ""


# ---------------------------------------------------------------- 8 Supervisor
with tabs[7]:
    st.subheader("Supervisor")
    st.caption("One read-only pass. It adds notes for you and cannot change the spec, the code, or a number.")
    if kb is None or paper_id is None:
        st.info("Select a paper to see supervisor notes and the agent trace.")
    else:
        try:
            notes = [i for i in kb.list_review_items(paper_id) if i["kind"] == "supervisor"]
        except Exception as e:  # noqa: BLE001
            notes = []
            err(e)
        if not notes:
            st.info("No supervisor notes yet. They appear after a thorough extraction.")
        for it in notes:
            body = it["item"]
            st.markdown(f"**{body.get('severity', 'info')}** `{it['path']}`")
            st.write(body.get("finding") or "No detail recorded.")
            st.caption(f"Status: {it['status']}. Dismiss it on the Review queue when you have read it.")
        st.subheader("Agent trace")
        try:
            trace_rows = []
            for rec in kb.trace_list(paper_id):
                label = _step_label(rec["step"])
                if not label:
                    continue
                usage = kb.trace_get(paper_id, f"usage_{rec['step']}") or {}
                trace_rows.append({
                    "step": label,
                    "tokens in": int(usage.get("input_tokens") or 0),
                    "tokens out": int(usage.get("output_tokens") or 0),
                    "seconds": round(float(usage.get("duration_ms") or 0) / 1000, 1),
                    "when": rec["created"],
                })
            if trace_rows:
                st.dataframe(pd.DataFrame(trace_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No agent steps for this paper yet.")
            cursor = kb.trace_get(paper_id, "cursor") or {}
            if cursor:
                st.caption(f"Last stage: {cursor.get('state', 'unknown')} ({cursor.get('mode', 'thorough')}).")
        except Exception as e:  # noqa: BLE001
            err(e)
    with st.expander("Token log"):
        lp = ROOT / "reports" / "llm_usage.jsonl"
        rows = []
        if lp.exists():
            for line in lp.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass
        if rows:
            d = pd.DataFrame(rows)
            for c in ("duration_ms", "input_tokens", "output_tokens", "cache_hit"):
                if c not in d.columns:
                    d[c] = 0
            d["cache_hit"] = d["cache_hit"].fillna(False).astype(int)
            g = d.groupby("role").agg(calls=("role", "size"), cache_hits=("cache_hit", "sum"),
                                      input_tokens=("input_tokens", "sum"), output_tokens=("output_tokens", "sum"),
                                      seconds=("duration_ms", lambda s: round(s.sum() / 1000, 1))).reset_index()
            st.dataframe(g, use_container_width=True, hide_index=True)
        else:
            st.caption("No model calls have been logged.")

# ---------------------------------------------------------------- 9 Review queue
with tabs[8]:
    st.subheader("Review queue")
    st.caption("Open disagreements, failed checks, and supervisor notes. Start extraction on Paper & spec, not here. "
               "An auto-settled field can be undone.")
    if kb is None or paper_id is None:
        st.info("Select a paper in the sidebar.")
    else:
        try:
            from replicator.agents.orchestrator import apply_review_choice
            queued = kb.list_review_items(paper_id)
        except Exception as e:  # noqa: BLE001
            queued = []
            err(e)
        if not queued:
            st.info("Nothing is waiting. Run thorough extraction on Paper & spec when you want two analysts to compare the paper.")
        for it in queued:
            body = it["item"]
            with st.container(border=True):
                st.markdown(f"**{it['kind'].replace('_', ' ')}** `{it['path']}`")
                st.caption(f"Status: {it['status']}")
                if it["kind"] == "supervisor":
                    st.write(body.get("finding") or "")
                    if it["status"] == "open" and st.button("Dismiss", key=f"dis{it['id']}"):
                        kb.set_review_status(it["id"], "dismissed")
                        st.rerun()
                    continue
                if it["kind"] == "failed_check":
                    st.write(body.get("reason") or body.get("issue") or "A citation check failed.")
                else:
                    st.write(f"Analyst A: `{body.get('a_value')}`")
                    st.write(f"Analyst B: `{body.get('b_value')}`")
                    dec_ = body.get("decision") or {}
                    if dec_:
                        st.caption(f"Reviewer chose {dec_.get('choice', '—')}. {dec_.get('reason', '')}")
                    if body.get("reason"):
                        st.caption(body["reason"])
                    if body.get("evidence"):
                        st.caption(f"p.{body['evidence'].get('page')}: \"{body['evidence'].get('quote', '')}\"")
                if it["kind"] == "auto_settled" and it["status"] == "settled":
                    if st.button("Undo settlement", key=f"rev{it['id']}"):
                        if spec is None:
                            st.error("Select a spec version before undoing a settlement.")
                        else:
                            choice = (body.get("decision") or {}).get("choice")
                            other = "A" if choice == "B" else "B"
                            updated = apply_review_choice(spec, body, other)
                            kb.add_spec(paper_id, updated, "edited", parent_id=spec_id, note=f"undid {it['path']}")
                            kb.set_review_status(it["id"], "reversed")
                            st.rerun()
                    continue
                if it["status"] != "open":
                    continue
                if it["kind"] != "failed_check":
                    c1, c2, c3 = st.columns(3)
                    if c1.button("Use analyst A", key=f"ua{it['id']}"):
                        if spec is None:
                            st.error("Select a spec version before applying a decision.")
                        else:
                            updated = apply_review_choice(spec, body, "A")
                            kb.add_spec(paper_id, updated, "edited", parent_id=spec_id, note=f"chose A for {it['path']}")
                            kb.set_review_status(it["id"], "accepted")
                            st.rerun()
                    if c2.button("Use analyst B", key=f"ub{it['id']}"):
                        if spec is None:
                            st.error("Select a spec version before applying a decision.")
                        else:
                            updated = apply_review_choice(spec, body, "B")
                            kb.add_spec(paper_id, updated, "edited", parent_id=spec_id, note=f"chose B for {it['path']}")
                            kb.set_review_status(it["id"], "accepted")
                            st.rerun()
                    if c3.button("Reject", key=f"rj{it['id']}"):
                        kb.set_review_status(it["id"], "rejected")
                        st.rerun()
                    st.caption("Reject leaves analyst A's value in place.")
                elif st.button("Reject", key=f"rj{it['id']}"):
                    kb.set_review_status(it["id"], "rejected")
                    st.rerun()
                typed = st.text_input("Or set a different value", key=f"val{it['id']}")
                if typed and st.button("Save value", key=f"sv{it['id']}"):
                    if spec is None:
                        st.error("Select a spec version before saving a value.")
                    else:
                        try:
                            parsed = json.loads(typed)
                        except Exception:  # noqa: BLE001
                            parsed = typed
                        updated = apply_review_choice(spec, body, parsed)
                        kb.add_spec(paper_id, updated, "edited", parent_id=spec_id, note=f"set {it['path']}")
                        kb.set_review_status(it["id"], "resolved")
                        st.rerun()
