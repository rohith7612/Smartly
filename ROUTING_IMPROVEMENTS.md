# Routing System Improvements

## Status Legend
- [ ] Pending
- [x] Done
- [~] In Progress

---

## Item 1 — Benchmark command: populate cost, variance, and quality fields
**Status:** [x]

`ModelBenchmarkStats` has `avg_cost`, `latency_variance`, `hallucination_rate`, `avg_quality_score` but the benchmark command never writes them. The risk predictor falls back to guesses for cost.

**Plan:**
- Count tokens during benchmarking using `extract_task_features`
- Calculate actual cost from token count × model prices
- Record `latency_variance` (stddev of the 3 samples)
- Store `avg_cost` in `ModelBenchmarkStats`

---

## Item 2 — Isolate MiniMax-M2 as judge-only model
**Status:** [x]

MiniMax-M2 is the hallucination judge. It's already excluded from being audited but the router can still select it for regular user tasks, which is undesirable.

**Plan:**
- Add `is_judge_model = BooleanField(default=False)` to `ModelProfile`
- Create migration for new field
- Set `MiniMaxAI/MiniMax-M2:novita` as `is_judge_model=True`
- Filter it out of auto-routing candidates in `minimax_router.py`
- Call it directly in the hallucination auditor

**Requires migration.**

---

## Item 3 — Replace gemini-2.0-flash with gemini-2.5-flash
**Status:** [x]

`gemini-2.0-flash` has `limit: 0` on free tier and fails every request. `gemini-2.5-flash` works.

**Plan:**
- Set `gemini-2.0-flash` → `is_active=False` via migration
- Add `models/gemini-2.5-flash` to `ModelProfile` via migration

**Requires migration.**

---

## Item 4 — Phase 9: Admin Monitoring Dashboard
**Status:** [x]

`ModelRuntimeStats` already collects all data needed. Just needs surfacing.

**Plan:**
- Add a Django admin view (or simple `/router/stats/` endpoint)
- Show:
  - Model usage distribution (count per model)
  - Average latency per model
  - Average cost per model
  - Hallucination score trends
  - Routing decision breakdown (auto vs static)

---

## Item 5 — Make benchmark sample count configurable
**Status:** [x]

Hardcoded to 3 samples. Plan spec says "N samples (configurable)".

**Plan:**
- Add `--samples` argument to `benchmark_models` management command
- Default to 3 to preserve existing behaviour

---

## Order of Implementation
1. Item 3 (gemini swap) — quick migration, unblocks clean benchmarking
2. Item 2 (judge model isolation) — correctness fix
3. Item 1 (benchmark cost/variance) — improves router accuracy
4. Item 5 (configurable samples) — small quality-of-life improvement
5. Item 4 (admin dashboard) — largest item, needs UI decisions
