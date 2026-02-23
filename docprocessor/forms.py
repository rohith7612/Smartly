from django import forms
from .models import Document, YouTubeVideo

class DocumentUploadForm(forms.ModelForm):
    file = forms.FileField(widget=forms.FileInput(attrs={'class': 'form-control'}))
    
    class Meta:
        model = Document
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
        }

class DocumentSelectForm(forms.Form):
    document = forms.ModelChoiceField(
        queryset=Document.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Document.objects.all()
        if user and getattr(user, 'is_authenticated', False):
            qs = Document.objects.filter(user=user)
        self.fields['document'].queryset = qs.order_by('-uploaded_at')

class DocumentMultiSelectForm(forms.Form):
    documents = forms.ModelMultipleChoiceField(
        queryset=Document.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Document.objects.all()
        if user and getattr(user, 'is_authenticated', False):
            qs = Document.objects.filter(user=user)
        self.fields['documents'].queryset = qs.order_by('-uploaded_at')

class YouTubeURLForm(forms.ModelForm):
    class Meta:
        model = YouTubeVideo
        fields = ['url']
        widgets = {
            'url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Enter YouTube URL'}),
        }

class ModelSelectionForm(forms.Form):
    """Dropdown to select AI model/provider used across features (except Library)."""
    MODEL_CHOICES = [
        ('auto', 'Auto (MiniMax Optimizer)'),
        ('gpt-3.5-turbo', 'OpenAI — GPT-3.5 Turbo'),
        ('gpt-4', 'OpenAI — GPT-4'),
        ('gpt-4o', 'OpenAI — GPT-4o'),
        ('gpt-4o-mini', 'OpenAI — GPT-4o Mini'),
        ('claude-3-haiku-20240307', 'Claude — 3 Haiku'),
        ('models/gemini-2.5-flash', 'Gemini — 2.5 Flash'),
        ('models/gemini-2.0-flash', 'Gemini — 2.0 Flash'),
        ('MiniMaxAI/MiniMax-M2:novita', 'Hugging Face — MiniMax M2 Novita'),
    ]
    ai_model = forms.ChoiceField(choices=MODEL_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, initial_model=None, **kwargs):
        super().__init__(*args, **kwargs)
        if initial_model:
            self.fields['ai_model'].initial = initial_model