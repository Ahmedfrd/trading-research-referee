"""Role cards. Code runs the workflow; each model role has one job and a typed output."""
from __future__ import annotations

ROLES: dict[str, dict] = {
    "extract_spec": {
        "title": "Analyst A",
        "stage": "extraction",
        "job": "Read the paper front to back and fill a spec.",
        "sees": "Page-marked paper text.",
        "forbidden": "Inventing a number, or writing strategy code.",
    },
    "analyst_b": {
        "title": "Analyst B",
        "stage": "extraction",
        "job": "Fill the same spec from a different reading order. Blind to analyst A.",
        "sees": "Page-marked paper text, last pages first.",
        "forbidden": "Seeing analyst A's spec or reasoning.",
    },
    "spec_reviewer": {
        "title": "Spec reviewer",
        "stage": "extraction",
        "job": "Pick A, B, neither, or ambiguous for each disagreement, with a quote.",
        "sees": "The two values and the cited pages. Not the analysts' reasoning.",
        "forbidden": "Inventing a third value.",
    },
    "reviser": {
        "title": "Reviser",
        "stage": "extraction",
        "job": "Replace fields whose citations failed the code check. At most two rounds.",
        "sees": "The failed checks and the cited pages.",
        "forbidden": "Changing a field the code check did not flag.",
    },
    "supervisor": {
        "title": "Supervisor",
        "stage": "extraction",
        "job": "One read-only pass. Add findings to the review queue.",
        "sees": "The spec summary, citation checks, and review items.",
        "forbidden": "Editing the spec, the code, or any number.",
    },
    "strategy_page": {
        "title": "Strategy-page writer",
        "stage": "strategy page",
        "job": "Draft the readable page. Every paper sentence needs a quote.",
        "sees": "The spec and the paper.",
        "forbidden": "Stating a result that is not in the spec.",
    },
    "fact_checker": {
        "title": "Fact-checker",
        "stage": "strategy page",
        "job": "Say whether each quote supports that sentence. Read-only.",
        "sees": "The sentences and their quotes.",
        "forbidden": "Rewriting the page.",
    },
    "results_analyst": {
        "title": "Results analyst",
        "stage": "results",
        "job": "Describe the gap using only numbers already in the computed table.",
        "sees": "The comparison table, gap reasons, and stats.",
        "forbidden": "Computing a new number.",
    },
}
