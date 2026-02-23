from .models import ModelBenchmarkStats, ModelRuntimeStats
from django.utils import timezone
from datetime import timedelta

def predict_reliability_risk(model):
    # ... (existing code)
    if recent_errors >= 2:
        return 1.0
    return recent_errors * 0.4

def compute_hallucination_score(source_text, generated_text):
    """
    Uses the MiniMax model as a judge to score the hallucination level of a result.
    Returns a float between 0 and 1.
    """
    from docprocessor.utils import _route_chat
    import json
    
    # We use MiniMax specifically as the 'Ground Truth' judge
    judge_model = "MiniMaxAI/MiniMax-M2:novita"
    
    prompt = f"""
    Compare the Source Text with the Generated Text. 
    Assign a 'Hallucination Score' from 0.0 (Perfectly Accurate) to 1.0 (Completely Fabricated).
    Fabrication includes adding info not in the source or contradicting the source.
    
    Source Text: {source_text[:4000]}
    Generated Text: {generated_text[:2000]}
    
    Return ONLY a JSON object: {{"score": float, "reason": "string"}}
    """
    
    try:
        response = _route_chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a strict fact-checker.",
            model=judge_model
        )
        # Extract JSON from response
        import re
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return float(data.get('score', 0.0))
    except Exception:
        pass
    return 0.0 # Default to safe if judge fails

def predict_cost(model, features):
    """
    Predict the cost of running a task on a specific model.
    """
    input_cost = (features["token_count"] / 1000) * model.price_per_1k_input_tokens
    output_cost = (features["requested_output_length"] / 1000) * model.price_per_1k_output_tokens
    return input_cost + output_cost

def predict_latency(model, features):
    """
    Predict latency based on benchmark data if available, otherwise use a linear model.
    """
    # Try to get data from real benchmarks first
    benchmark = ModelBenchmarkStats.objects.filter(model=model, task_type=features["task_type"]).first()
    
    if benchmark and benchmark.avg_latency > 0:
        # Scale benchmark latency by token count (assuming benchmark was ~500 tokens)
        scale_factor = features["token_count"] / 500
        return benchmark.avg_latency * max(0.5, scale_factor)

    # Fallback to linear model if no benchmark data exists
    base_latency = 1.0 # seconds
    per_token_factor = 0.002 # seconds per token
    
    # Adjust based on provider (rough estimates)
    provider_multiplier = {
        'openai': 1.0,
        'anthropic': 1.2,
        'google': 0.8,
        'hf': 1.5
    }
    multiplier = provider_multiplier.get(model.provider, 1.0)
    
    return (base_latency + (features["token_count"] * per_token_factor)) * multiplier

def predict_hallucination(model, features):
    """
    Predict probability of hallucination.
    """
    complexity_factor = 1.0

    # Task type risk
    if features["task_type"] == "analyze":
        complexity_factor += 0.2
    elif features["task_type"] == "generate":
        complexity_factor += 0.1

    # Semantic density risk (higher density = harder to summarize accurately)
    if features["semantic_density"] > 0.6:
        complexity_factor += 0.15

    # Context length risk
    if features["token_count"] > 10000:
        complexity_factor += 0.25

    # Mitigation
    if features.get("focus_mode_enabled"):
        complexity_factor -= 0.30

    return max(0.0, model.base_hallucination_rate * complexity_factor)

def predict_overflow(model, features):
    """
    Predict context overflow risk. 
    1.0 means full, > 1.0 means overflow.
    """
    return features["token_count"] / model.max_context_tokens
