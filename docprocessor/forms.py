from django import forms
from .models import Document, YouTubeVideo

class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'file']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
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

class TranslationForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}))
    source_language = forms.ChoiceField(
        choices=[
            ('auto', 'Auto-detect'),
            ('en', 'English'),
            ('es', 'Spanish'),
            ('fr', 'French'),
            ('de', 'German'),
            ('zh', 'Chinese'),
            ('ja', 'Japanese'),
            ('ko', 'Korean'),
            ('hi', 'Hindi'),
            ('ar', 'Arabic'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    target_language = forms.ChoiceField(
        choices=[
            ('en', 'English'),
            ('es', 'Spanish'),
            ('fr', 'French'),
            ('de', 'German'),
            ('zh', 'Chinese'),
            ('ja', 'Japanese'),
            ('ko', 'Korean'),
            ('hi', 'Hindi'),
            ('ar', 'Arabic'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )