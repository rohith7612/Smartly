from .risk_predictor import predict_cost, predict_latency, predict_hallucination, predict_overflow, predict_reliability_risk
from .normalizer import normalize_risks
from .models import ModelProfile

def select_model(task_features):
    """
    Select the best model using MiniMax optimization.
    """
    candidate_models = ModelProfile.objects.filter(is_active=True)
    
    if not candidate_models.exists():
        return None # Fallback to hardcoded default elsewhere
    
    model_risks = []
    valid_models = []
    
    for model in candidate_models:
        overflow = predict_overflow(model, task_features)
        if overflow > 1.0:
            continue
            
        cost = predict_cost(model, task_features)
        latency = predict_latency(model, task_features)
        hallucination = predict_hallucination(model, task_features)
        reliability = predict_reliability_risk(model)
        
        valid_models.append(model)
        model_risks.append([cost, latency, hallucination, reliability, overflow])
        
    if not valid_models:
        # If all overflow, pick the one with the largest context
        return candidate_models.order_by('-max_context_tokens').first()
        
    normalized = normalize_risks(model_risks)
    
    results = []
    for i, model in enumerate(valid_models):
        # MiniMax: Minimize the Maximum Risk
        worst_case_risk = max(normalized[i])
        results.append((model, worst_case_risk, model_risks[i][0])) # model, risk, cost for tie-break
        
    # Sort by worst_case_risk, then by cost as tie-breaker
    results.sort(key=lambda x: (x[1], x[2]))
    
    return results[0][0]
