import re
from functools import lru_cache

@lru_cache(maxsize=8)
def _get_tiktoken_encoding(model_name):
    try:
        import tiktoken
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None

def estimate_tokens(text, model_name="gpt-3.5-turbo"):
    """Estimate token count for a given text."""
    encoding = _get_tiktoken_encoding(model_name)
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:
            pass
    return int(len(text.split()) * 1.3)

def compute_semantic_density(text):
    """
    Estimate semantic density of the text.
    Simplified: Ratio of unique non-stop words to total words.
    """
    words = re.findall(r'\w+', text.lower())
    if not words:
        return 0.0
    
    unique_words = set(words)
    # Basic density: unique words / total words
    # More sophisticated would use embeddings, but this is a good O(n) proxy.
    return len(unique_words) / len(words)

def extract_task_features(text, task_type, focus_mode=False, requested_output_length=500):
    """
    Extract features from the task to inform routing decisions.
    """
    token_count = estimate_tokens(text)
    semantic_density = compute_semantic_density(text)
    
    return {
        "token_count": token_count,
        "task_type": task_type,
        "semantic_density": semantic_density,
        "requested_output_length": requested_output_length,
        "focus_mode_enabled": focus_mode
    }
