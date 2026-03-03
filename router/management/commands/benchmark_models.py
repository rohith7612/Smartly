from django.core.management.base import BaseCommand
from router.models import ModelProfile, ModelBenchmarkStats
from router.task_features import extract_task_features
from docprocessor.utils import _route_chat
import time
import math

class Command(BaseCommand):
    help = 'Run benchmarks for all active models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--samples',
            type=int,
            default=3,
            help='Number of samples per task type (default: 3)',
        )

    def handle(self, *args, **options):
        num_samples = options['samples']
        models = ModelProfile.objects.filter(is_active=True, is_judge_model=False)
        task_types = ['summarize', 'generate', 'analyze']

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
                costs = []
                for i in range(num_samples):
                    start = time.time()
                    try:
                        self.stdout.write(f"    Running sample {i+1}/{num_samples}...")
                        prompt = samples[task_type]
                        _route_chat(
                            messages=[{"role": "user", "content": prompt}],
                            system_prompt=f"Task: {task_type}",
                            model=model.model_name
                        )
                        elapsed = time.time() - start
                        latencies.append(elapsed)

                        # Estimate cost from token count
                        features = extract_task_features(prompt, task_type)
                        input_tokens = features['token_count']
                        output_tokens = features.get('requested_output_length', 200)
                        cost = (input_tokens / 1000 * model.price_per_1k_input_tokens) + \
                               (output_tokens / 1000 * model.price_per_1k_output_tokens)
                        costs.append(cost)

                        if i < num_samples - 1:
                            time.sleep(5)
                    except Exception as e:
                        self.stderr.write(f"    Error benchmarking {model.model_name}: {e}")
                        time.sleep(10)

                if latencies:
                    avg_latency = sum(latencies) / len(latencies)
                    avg_cost = sum(costs) / len(costs) if costs else 0.0
                    variance = (
                        math.sqrt(sum((l - avg_latency) ** 2 for l in latencies) / len(latencies))
                        if len(latencies) > 1 else 0.0
                    )
                    ModelBenchmarkStats.objects.update_or_create(
                        model=model,
                        task_type=task_type,
                        defaults={
                            'avg_latency': avg_latency,
                            'latency_variance': variance,
                            'avg_cost': avg_cost,
                            'sample_size': len(latencies),
                        }
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"    Avg Latency: {avg_latency:.2f}s | Variance: {variance:.2f}s | Avg Cost: ${avg_cost:.6f}"
                    ))
