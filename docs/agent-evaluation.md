# Agent evaluation (offline fixtures, 2026-10-19)

This is the fault catalogue from plan §11.7, run with fixture model outputs. No live Claude call was made, so there is no token or time measurement against the subscription. A role is not dropped or kept on a live score. The table is what the code checks catch when two readings agree, and what the second reading catches when they do not.

| Planted fault | What catches it |
|---|---|
| Analysts disagree on formation length, and the quote contains only one of the values | Field diff, then the clear-cut rule. The other value is not invented. |
| Disagreement on sample start, variant, universe, or a raw-versus-alpha label | Always escalated. A person decides. |
| Reviser quote is not on the cited page | The patch is not applied. After two rounds the field stays in the review queue. |
| Both analysts label a CAPM-alpha quote as a raw return | The diff is empty. `mislabelled_alpha` flags it. Agreement is not treated as proof. |
| Generated source contains `shift(-1)` | Static leak lint. The look-ahead harness remains the real check. |
| A gap paragraph quotes a number that is not in the computed table | Number check withholds the paragraph. The model is not asked to recompute. |
| The model call reports a usage limit after analyst A | The run pauses. The next run reuses analyst A and continues. |

The coder does not emit strategy code. Families outside the templates are refused. The experimental supervisor adds notes to the queue and cannot change the spec, the code, or a number.

Covered by `tests/rp/test_agents.py` and `tests/rp/test_thorough_path.py`.
