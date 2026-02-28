from celery import shared_task
from django.db.models import Avg, StdDev, Count
from .models import ModelProfile, ModelBenchmarkStats, ModelRuntimeStats
import logging

logger = logging.getLogger(__name__)

from .risk_predictor import compute_hallucination_score

@shared_task
def audit_hallucination_task(runtime_stat_id, source_text, generated_text):
    """
    Asynchronously compute hallucination score using the Judge model.
    """
    try:
        score = compute_hallucination_score(source_text, generated_text)
        stat = ModelRuntimeStats.objects.get(id=runtime_stat_id)
        stat.hallucination_score = score
        stat.save()
        return f"Audited stat {runtime_stat_id} with score {score}"
    except Exception as e:
        return f"Audit failed: {e}"

@shared_task
def update_routing_priors():
    """
    Phase 8.4: Scheduled task to update benchmarks based on real runtime data.
    Ensures the router adapts to model drift or provider performance changes.
    """
    profiles = ModelProfile.objects.filter(is_active=True)
    
    for profile in profiles:
        # Aggregate stats from the last 24 hours of runtime data
        stats = ModelRuntimeStats.objects.filter(model=profile).values('task_type').annotate(
            avg_lat=Avg('actual_latency'),
            lat_var=StdDev('actual_latency'),
            avg_c=Avg('actual_cost'),
            count=Count('id')
        )
        
        for stat in stats:
            if stat['count'] > 5: # Only update if we have a significant sample
                ModelBenchmarkStats.objects.update_or_create(
                    model=profile,
                    task_type=stat['task_type'],
                    defaults={
                        'avg_latency': stat['avg_lat'],
                        'latency_variance': stat['lat_var'] or 0.0,
                        'avg_cost': stat['avg_c'],
                        'sample_size': stat['count']
                    }
                )
                logger.info(f"Updated benchmarks for {profile.model_name} ({stat['task_type']})")

    return "Routing priors updated successfully."
