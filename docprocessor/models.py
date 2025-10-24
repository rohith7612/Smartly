from django.db import models
from django.contrib.auth.models import User

class Document(models.Model):
    DOCUMENT_TYPES = (
        ('pdf', 'PDF'),
        ('docx', 'DOCX'),
        ('txt', 'TXT'),
        ('image', 'Image'),
    )
    
    PROCESSING_TYPES = (
        ('summarize', 'Summarize'),
        ('generate', 'Generate Answers'),
        ('analyze', 'Analyze'),
        ('translate', 'Translate'),
    )
    
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/')
    document_type = models.CharField(max_length=10, choices=DOCUMENT_TYPES)
    processing_type = models.CharField(max_length=20, choices=PROCESSING_TYPES)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        return self.title

class YouTubeVideo(models.Model):
    url = models.URLField()
    title = models.CharField(max_length=255, blank=True)
    transcript = models.TextField(blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        return self.title or self.url

class YouTubeProcessedResult(models.Model):
    PROCESSING_TYPES = (
        ('summarize', 'Summarize'),
        ('generate', 'Generate Answers'),
        ('analyze', 'Analyze'),
    )
    youtube_video = models.ForeignKey(YouTubeVideo, on_delete=models.CASCADE, related_name='processed_results')
    processing_type = models.CharField(max_length=20, choices=PROCESSING_TYPES)
    result_text = models.TextField()
    processed_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        base = self.youtube_video.title or self.youtube_video.url
        return f"{self.get_processing_type_display()} for {base}"

class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    documents = models.ManyToManyField(Document, blank=True, related_name='chat_sessions')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Chat #{self.id}"

class ChatMessage(models.Model):
    ROLE_CHOICES = (
        ('system', 'System'),
        ('user', 'User'),
        ('assistant', 'Assistant'),
    )
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"

class ProcessedResult(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='results')
    result_text = models.TextField()
    processed_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Result for {self.document.title}"
