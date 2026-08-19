# Test papers

PDFs are not committed — they are third-party academic work, so this
repository links to them rather than redistributing them.

## Negative control

`negative_control_school_autonomy.pdf` is used to verify that the extractor
**refuses** documents that are not trading-strategy papers, instead of
hallucinating a strategy from them. It is an education-economics paper with
no trading content whatsoever.

Fetch it with:

```bash
curl -L -A "Mozilla/5.0" \
  -o data/papers/negative_control_school_autonomy.pdf \
  "https://www.nber.org/system/files/working_papers/w17591/w17591.pdf"
```

> Hanushek, Link & Woessmann (2011), *Does School Autonomy Make Sense
> Everywhere? Panel Estimates from PISA*, NBER Working Paper 17591.

Expected behaviour: every extracted field comes back marked `assumed` with an
empty quote, evidence strength falls below the 25% gate, and the audit refuses
to produce a backtest.

## Validation data

The AQR factor spreadsheets used to validate the engine are downloaded on
demand into `data/cache/` and are likewise not committed. See `README.md`.
