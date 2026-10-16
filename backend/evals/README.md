# Extraction evaluation

Measures how well the chunk and finish graphs turn dictation into the report.
Run it before changing the prompt, the model, validation, or `TURN_SILENCE_MS`.

```bash
cd backend
python evals/run_eval.py                    # run, compare with baseline.json
python evals/run_eval.py --update-baseline  # accept this run as the new baseline
```

Needs `GROQ_API_KEY` in `backend/.env`. It calls the real LLM, so it costs a few
requests per case. It does not touch AssemblyAI, the database, or the server.

## What it checks

`cases.json` holds de-identified, hand-written dictations as text chunks, with
expectations:

- `expect`: field → phrases that must appear in that field. `a|b` means either.
- `forbid`: phrases that must not appear anywhere in the report (invented content).
- `expect_empty`: no report content at all (for non-report speech).
- `expect_comment_source`: allowed `comment_source` values.

For each run it reports:

| Metric | Meaning |
|---|---|
| field recall | expected phrases found in the right field |
| misroute rate | expected phrases found only in a different field |
| forbidden hits | forbidden phrases found |
| invented problems | grounding failures (numbers, units, laterality, negations not in the dictation) in fields the model wrote |
| rejected chunks | chunks the graph rejected after repair |
| latency p50/p95 | per chunk and finalize, successful attempt only |

## Regression gate

Exit code 1 when, against `baseline.json`, field recall drops by more than 0.05,
misroute rate rises by more than 0.05, forbidden hits or invented problems rise
(invented: by more than 1), or rejected chunks rise by more than 1.

LLM output varies between runs. A single failing run is a signal to repeat, not
proof of a regression.

## Files

- `cases.json`: the cases. Keep them de-identified and synthetic, or from real
  sessions only with consent. Add a case whenever a real failure is found.
- `baseline.json`: the accepted reference run (tracked in git).
- `results/`: per-run output (gitignored).

## Limits

- Text chunks, not audio. Speech-to-text accuracy is not measured here.
- Small set: 12 cases. Grow it to 30–50 from real, consented sessions.
- Free-tier LLM rate limits slow the run. Rate-limited calls are retried after a pause.
