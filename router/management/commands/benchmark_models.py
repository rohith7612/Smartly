from django.core.management.base import BaseCommand
from router.models import ModelProfile, ModelBenchmarkStats
from docprocessor.utils import _route_chat
import time

class Command(BaseCommand):
    help = 'Run benchmarks for all active models'

    def handle(self, *args, **options):
        models = ModelProfile.objects.filter(is_active=True)
        task_types = ['summarize', 'generate', 'analyze']
        
        # Sample dataset for benchmarking
        samples = {
            'summarize': "The routing system uses MiniMax optimization to minimize the maximum risk across multiple dimensions. It evaluates cost, latency, and hallucination risk to select the best model for a given task, ensuring robust and efficient AI orchestration.",
            'generate': "What are the core components of the MiniMax routing system?",
            'analyze': "Compare and contrast MiniMax routing with traditional round-robin LLM load balancing."
        }

        for model in models:
            self.stdout.write(f"Benchmarking model: {model.model_name}")
            for task_type in task_types:
                self.stdout.write(f"  Task type: {task_type}")
                
                latencies = []
                for i in range(3): # 3 samples per task
                    start = time.time()
                    try:
                        self.stdout.write(f"    Running sample {i+1}/3...")
                        # Use _route_chat directly to measure real performance
                        _route_chat(
                            messages=[{"role": "user", "content": samples[task_type]}],
                            system_prompt=f"Task: {task_type}",
                            model=model.model_name
                        )
                        latencies.append(time.time() - start)
                        
                        # Add a delay to respect rate limits (especially for Gemini/Free tiers)
                        if i < 2:
                            time.sleep(5) 
                    except Exception as e:
                        self.stderr.write(f"    Error benchmarking {model.model_name}: {e}")
                        time.sleep(10) # Longer sleep on error

                if latencies:
                    avg_latency = sum(latencies) / len(latencies)
                    ModelBenchmarkStats.objects.update_or_create(
                        model=model,
                        task_type=task_type,
                        defaults={
                            'avg_latency': avg_latency,
                            'sample_size': len(latencies)
                        }
                    )
                    self.stdout.write(self.style.SUCCESS(f"    Avg Latency: {avg_latency:.2f}s"))
