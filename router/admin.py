from django.contrib import admin
from .models import ModelProfile, ModelBenchmarkStats, ModelRuntimeStats

@admin.register(ModelProfile)
class ModelProfileAdmin(admin.ModelAdmin):
    list_display = ('model_name', 'provider', 'price_per_1k_input_tokens', 'price_per_1k_output_tokens', 'is_active')
    list_filter = ('provider', 'is_active')
    search_fields = ('model_name',)

@admin.register(ModelBenchmarkStats)
class ModelBenchmarkStatsAdmin(admin.ModelAdmin):
    list_display = ('model', 'task_type', 'avg_latency', 'hallucination_rate', 'sample_size')
    list_filter = ('task_type', 'model')

@admin.register(ModelRuntimeStats)
class ModelRuntimeStatsAdmin(admin.ModelAdmin):
    list_display = ('model', 'task_type', 'actual_latency', 'actual_cost', 'created_at')
    list_filter = ('model', 'task_type', 'created_at')
    readonly_fields = ('created_at',)
