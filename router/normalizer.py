def normalize_risks(risk_matrix):
    """
    Apply min-max scaling across models for each risk dimension.
    risk_matrix is a list of lists: [[cost, latency, hallucination], ...]
    Returns a normalized matrix where each value is [0, 1].
    """
    if not risk_matrix:
        return []
    
    num_dimensions = len(risk_matrix[0])
    num_models = len(risk_matrix)
    
    normalized_matrix = [[0.0] * num_dimensions for _ in range(num_models)]
    
    for d in range(num_dimensions):
        values = [row[d] for row in risk_matrix]
        min_val = min(values)
        max_val = max(values)
        
        range_val = max_val - min_val
        if range_val == 0:
            for m in range(num_models):
                normalized_matrix[m][d] = 0.5 # Neutral if all are the same
        else:
            for m in range(num_models):
                normalized_matrix[m][d] = (risk_matrix[m][d] - min_val) / range_val
                
    return normalized_matrix
