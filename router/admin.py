from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.db.models import Avg, Count
from .models import ModelProfile, ModelBenchmarkStats, ModelRuntimeStats


def routing_stats_view(request):
    # --- Summary cards ---
    runtime_qs = ModelRuntimeStats.objects.all()
    total_requests = runtime_qs.count()

    agg = runtime_qs.aggregate(
        avg_latency=Avg('actual_latency'),
        avg_cost=Avg('actual_cost'),
        avg_halluc=Avg('hallucination_score'),
    )
    active_models = ModelProfile.objects.filter(is_active=True, is_judge_model=False).count()

    summary = {
        'total_requests': total_requests,
        'avg_latency': round(agg['avg_latency'] or 0, 2),
        'avg_cost': f"{agg['avg_cost'] or 0:.6f}",
        'avg_halluc': round((agg['avg_halluc'] or 0) * 100, 1),
        'active_models': active_models,
    }

    # --- Usage distribution rows ---
    per_model = (
        runtime_qs
        .values('model__model_name', 'model__provider')
        .annotate(
            count=Count('id'),
            avg_latency=Avg('actual_latency'),
            avg_cost=Avg('actual_cost'),
            avg_halluc=Avg('hallucination_score'),
        )
        .order_by('-count')
    )

    max_latency = max((r['avg_latency'] or 0 for r in per_model), default=1) or 1
    max_cost    = max((r['avg_cost'] or 0 for r in per_model), default=1) or 1
    max_count   = max((r['count'] for r in per_model), default=1) or 1

    usage_rows = []
    for r in per_model:
        avg_halluc = r['avg_halluc']
        usage_rows.append({
            'model_name':  r['model__model_name'],
            'provider':    r['model__provider'],
            'count':       r['count'],
            'usage_pct':   round(r['count'] / max_count * 100),
            'avg_latency': round(r['avg_latency'] or 0, 2),
            'latency_pct': round((r['avg_latency'] or 0) / max_latency * 100),
            'avg_cost':    f"{r['avg_cost'] or 0:.6f}",
            'cost_pct':    round((r['avg_cost'] or 0) / max_cost * 100),
            'avg_halluc':  round((avg_halluc or 0) * 100, 1) if avg_halluc is not None else None,
            'halluc_pct':  round((avg_halluc or 0) * 100) if avg_halluc is not None else 0,
        })

    # --- Benchmark rows ---
    benchmark_rows = (
        ModelBenchmarkStats.objects
        .values('model__model_name', 'task_type', 'avg_latency', 'latency_variance', 'avg_cost', 'sample_size')
        .order_by('model__model_name', 'task_type')
    )

    # --- Recent routing decisions ---
    recent_rows = (
        ModelRuntimeStats.objects
        .values('model__model_name', 'task_type', 'actual_latency', 'actual_cost', 'hallucination_score', 'created_at')
        .order_by('-created_at')[:20]
    )

    context = {
        **admin.site.each_context(request),
        'title': 'Routing Performance Dashboard',
        'summary': summary,
        'usage_rows': usage_rows,
        'benchmark_rows': benchmark_rows,
        'recent_rows': recent_rows,
    }
    return render(request, 'admin/router/routing_stats.html', context)


@admin.register(ModelProfile)
class ModelProfileAdmin(admin.ModelAdmin):
    list_display  = ('model_name', 'provider', 'price_per_1k_input_tokens', 'price_per_1k_output_tokens', 'is_active', 'is_judge_model')
    list_filter   = ('provider', 'is_active', 'is_judge_model')
    search_fields = ('model_name',)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('stats/', self.admin_site.admin_view(routing_stats_view), name='routing_stats'),
        ]
        return custom + urls


@admin.register(ModelBenchmarkStats)
class ModelBenchmarkStatsAdmin(admin.ModelAdmin):
    list_display = ('model', 'task_type', 'avg_latency', 'latency_variance', 'avg_cost', 'hallucination_rate', 'sample_size')
    list_filter  = ('task_type', 'model')


@admin.register(ModelRuntimeStats)
class ModelRuntimeStatsAdmin(admin.ModelAdmin):
    list_display   = ('model', 'task_type', 'actual_latency', 'actual_cost', 'hallucination_score', 'created_at')
    list_filter    = ('model', 'task_type', 'created_at')
    readonly_fields = ('created_at',)
