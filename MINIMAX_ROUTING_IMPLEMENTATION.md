```
MINIMAX_ROUTING_IMPLEMENTATION.md
```

---

# MiniMax-Based Multi-LLM Routing Implementation Plan

## Smartly Enhancement Roadmap

---

## 📌 Project Objective

Enhance the existing **Smartly Django backend** by implementing a **MiniMax-based multi-LLM routing system** that dynamically selects the most robust model for each task based on predicted risk:

* Cost
* Latency
* Hallucination probability
* Context overflow risk

The system must:

1. Benchmark models offline
2. Predict runtime risk per model per task
3. Apply MiniMax optimization
4. Log runtime performance
5. Continuously improve predictions
6. Remain modular and production-safe

---

# 🏗 System Overview

```
User Request
     ↓
Task Feature Extractor
     ↓
Risk Estimation Layer
     ↓
MiniMax Optimizer
     ↓
Selected Model
     ↓
LLM Inference
     ↓
Performance Logger
     ↓
Risk Model Updater
```

This routing layer integrates inside Smartly’s existing AI Integration Layer.

---

# 🔹 PHASE 1 — Database Schema

### 1️⃣ ModelProfile

Stores static model metadata.

Fields:

* id
* model_name (string)
* provider (string)
* price_per_1k_input_tokens (float)
* price_per_1k_output_tokens (float)
* max_context_tokens (int)
* base_hallucination_rate (float)
* created_at
* updated_at

---

### 2️⃣ ModelBenchmarkStats

Stores offline benchmark statistics.

Fields:

* id
* model (ForeignKey → ModelProfile)
* task_type (string)
* avg_latency (float)
* latency_variance (float)
* avg_cost (float)
* avg_quality_score (float)
* hallucination_rate (float)
* sample_size (int)
* created_at

---

### 3️⃣ ModelRuntimeStats

Stores live execution metrics.

Fields:

* id
* model (ForeignKey → ModelProfile)
* task_type (string)
* actual_latency (float)
* actual_cost (float)
* hallucination_score (float)
* token_count (int)
* created_at

---

# 🔹 PHASE 2 — Offline Benchmarking System

Create Django management command:

```
python manage.py benchmark_models
```

### Responsibilities:

1. Load benchmark datasets per task type:

   * summarization
   * QA
   * long-context
   * transcript analysis

2. For each model:

   * Run N samples (configurable)
   * Measure:

     * input tokens
     * output tokens
     * latency
     * ROUGE or quality metric
     * hallucination score

3. Store aggregated statistics in `ModelBenchmarkStats`.

### Requirements:

* Reproducible runs
* Structured logging
* Fault isolation per model

---

# 🔹 PHASE 3 — Task Feature Extraction Module

Create:

```
smartly/router/task_features.py
```

Implement:

```python
def extract_task_features(request):
    return {
        "token_count": estimate_tokens(request.document),
        "task_type": request.task_type,
        "semantic_density": compute_semantic_density(request.document),
        "requested_output_length": request.word_limit,
        "focus_mode_enabled": request.focus_mode
    }
```

### Feature Definitions

* **Token Count** → tokenizer-based estimate
* **Semantic Density** → entropy or embedding variance
* **Task Type** → endpoint-based classification
* **Focus Mode** → reduces hallucination risk

---

# 🔹 PHASE 4 — Risk Prediction Module

Create:

```
smartly/router/risk_predictor.py
```

---

## 1️⃣ Cost Prediction

```python
def predict_cost(model, features):
    return (
        features["token_count"] * model.price_per_1k_input_tokens +
        features["requested_output_length"] * model.price_per_1k_output_tokens
    )
```

---

## 2️⃣ Latency Prediction

Initial linear model:

```
latency = a * token_count + b
```

Store coefficients per model in DB.

---

## 3️⃣ Hallucination Prediction

```python
def predict_hallucination(model, features):
    complexity_factor = 1.0

    if features["task_type"] == "abstractive":
        complexity_factor += 0.15

    if features["token_count"] > 20000:
        complexity_factor += 0.20

    if features["focus_mode_enabled"]:
        complexity_factor -= 0.30

    return model.base_hallucination_rate * complexity_factor
```

---

## 4️⃣ Context Overflow Risk

```python
def predict_overflow(model, features):
    return features["token_count"] / model.max_context_tokens
```

If > 1 → reject model.

---

# 🔹 PHASE 5 — Normalization Module

Create:

```
smartly/router/normalizer.py
```

Implement:

```python
def normalize_risks(risk_matrix):
    # Apply min-max scaling across models
    pass
```

Scale each risk dimension between 0 and 1.

---

# 🔹 PHASE 6 — MiniMax Router

Create:

```
smartly/router/minimax_router.py
```

```python
def select_model(task_features, candidate_models):

    risks = []

    for model in candidate_models:
        C = predict_cost(model, task_features)
        L = predict_latency(model, task_features)
        H = predict_hallucination(model, task_features)
        O = predict_overflow(model, task_features)

        if O > 1:
            continue

        normalized = normalize([C, L, H, O])
        worst_case = max(normalized)

        risks.append((model, worst_case))

    selected = min(risks, key=lambda x: x[1])
    return selected[0]
```

### Safety Rules

* If all models overflow → choose largest context model
* If tie → choose lower predicted cost
* Complexity must remain O(n_models)

---

# 🔹 PHASE 7 — Router Integration

Modify AI integration layer:

* If user selects **Auto (MiniMax)** → use router
* If user selects specific model → bypass router

Maintain backward compatibility.

---

# 🔹 PHASE 8 — Feedback Loop

After inference:

1. Measure:

   * actual_latency
   * actual_cost
   * output_token_count

2. Compute hallucination score:

   * Compare output against retrieved chunks (Focus Mode)
   * Or lightweight fact-check model

3. Store in `ModelRuntimeStats`.

4. Scheduled task (daily):

   * Update regression coefficients
   * Update hallucination priors
   * Detect drift

---

# 🔹 PHASE 9 — Monitoring Dashboard (Admin)

Add metrics view:

* Model usage distribution
* Cost savings vs static baseline
* Average latency per model
* Worst-case risk trends
* Routing decision heatmap

---

# 🔹 PHASE 10 — Experimental Mode

Add feature flag:

```
ENABLE_ROUTER_EXPERIMENT = True
```

Log:

* Static baseline decisions
* MiniMax decisions
* Performance comparison

Enable research evaluation.

---

# 🔹 Non-Functional Requirements

* Modular architecture
* No hard-coded model names
* Config-driven model registry
* Separation of:

  * Prediction
  * Optimization
  * Execution
* Structured logging
* Unit tests for:

  * Risk prediction
  * Normalization
  * MiniMax logic

---

# 🔹 Deployment Strategy

1. Deploy benchmarking first
2. Validate risk predictions manually
3. Enable MiniMax for 10% traffic
4. Monitor cost + latency
5. Gradually scale

---

# 🔹 Success Criteria

The system must demonstrate:

* Reduced average cost per request
* Reduced 95th percentile latency
* No increase in hallucination rate
* No context overflow failures

---

# 🔹 Future Extensions (Optional)

* Reinforcement learning router
* Risk-averse optimization using variance
* Multi-armed bandit selection
* Online regret minimization

---

# ✅ Final Outcome

Smartly evolves from:

> Multi-model platform

To:

> Self-optimizing, risk-aware, cost-efficient multi-LLM orchestration system.

---
