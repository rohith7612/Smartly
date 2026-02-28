from django.db import models

class ModelProfile(models.Model):
    model_name = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=50) # openai, anthropic, google, hf
    price_per_1k_input_tokens = models.FloatField(default=0.0)
    price_per_1k_output_tokens = models.FloatField(default=0.0)
    max_context_tokens = models.IntegerField(default=4096)
    base_hallucination_rate = models.FloatField(default=0.01) # 1% baseline
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider}: {self.model_name}"

class ModelBenchmarkStats(models.Model):
    TASK_TYPES = (
        ('summarize', 'Summarization'),
        ('generate', 'QA/Generation'),
        ('analyze', 'Analysis'),
        ('translate', 'Translation'),
        ('chat', 'Chat'),
    )
    model = models.ForeignKey(ModelProfile, on_delete=models.CASCADE, related_name='benchmarks')
    task_type = models.CharField(max_length=20, choices=TASK_TYPES)
    avg_latency = models.FloatField(default=0.0)
    latency_variance = models.FloatField(default=0.0)
    avg_cost = models.FloatField(default=0.0)
    avg_quality_score = models.FloatField(default=0.0) # 0 to 1
    hallucination_rate = models.FloatField(default=0.0)
    sample_size = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Benchmark: {self.model.model_name} for {self.task_type}"

class ModelRuntimeStats(models.Model):
    model = models.ForeignKey(ModelProfile, on_delete=models.CASCADE, related_name='runtime_stats')
    task_type = models.CharField(max_length=20)
    actual_latency = models.FloatField()
    actual_cost = models.FloatField()
    hallucination_score = models.FloatField(null=True, blank=True)
    token_count = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Runtime: {self.model.model_name} at {self.created_at}"
