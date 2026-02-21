from .forms import ModelSelectionForm

def selected_model(request):
    """Expose selected AI model and a friendly label to all templates."""
    model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    # Map to human-friendly label using form choices
    labels = dict(ModelSelectionForm.MODEL_CHOICES)
    label = labels.get(model, model)
    return {
        'selected_model': model,
        'selected_model_label': label,
    }