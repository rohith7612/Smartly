from django.db import migrations, models
import django.db.models.deletion

def seed_models(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.bulk_create([
        ModelProfile(
            model_name='gpt-3.5-turbo',
            provider='openai',
            price_per_1k_input_tokens=0.0005,
            price_per_1k_output_tokens=0.0015,
            max_context_tokens=16385,
            base_hallucination_rate=0.02
        ),
        ModelProfile(
            model_name='gpt-4o-mini',
            provider='openai',
            price_per_1k_input_tokens=0.00015,
            price_per_1k_output_tokens=0.0006,
            max_context_tokens=128000,
            base_hallucination_rate=0.015
        ),
        ModelProfile(
            model_name='claude-3-haiku-20240307',
            provider='anthropic',
            price_per_1k_input_tokens=0.00025,
            price_per_1k_output_tokens=0.00125,
            max_context_tokens=200000,
            base_hallucination_rate=0.01
        ),
        ModelProfile(
            model_name='gemini-2.0-flash',
            provider='google',
            price_per_1k_input_tokens=0.0001,
            price_per_1k_output_tokens=0.0004,
            max_context_tokens=1000000,
            base_hallucination_rate=0.02
        ),
    ])

class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ModelProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(max_length=100, unique=True)),
                ('provider', models.CharField(max_length=50)),
                ('price_per_1k_input_tokens', models.FloatField(default=0.0)),
                ('price_per_1k_output_tokens', models.FloatField(default=0.0)),
                ('max_context_tokens', models.IntegerField(default=4096)),
                ('base_hallucination_rate', models.FloatField(default=0.01)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='ModelRuntimeStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_type', models.CharField(max_length=20)),
                ('actual_latency', models.FloatField()),
                ('actual_cost', models.FloatField()),
                ('hallucination_score', models.FloatField(blank=True, null=True)),
                ('token_count', models.IntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('model', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='runtime_stats', to='router.modelprofile')),
            ],
        ),
        migrations.CreateModel(
            name='ModelBenchmarkStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_type', models.CharField(choices=[('summarize', 'Summarization'), ('generate', 'QA/Generation'), ('analyze', 'Analysis'), ('translate', 'Translation'), ('chat', 'Chat')], max_length=20)),
                ('avg_latency', models.FloatField(default=0.0)),
                ('latency_variance', models.FloatField(default=0.0)),
                ('avg_cost', models.FloatField(default=0.0)),
                ('avg_quality_score', models.FloatField(default=0.0)),
                ('hallucination_rate', models.FloatField(default=0.0)),
                ('sample_size', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('model', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='benchmarks', to='router.modelprofile')),
            ],
        ),
        migrations.RunPython(seed_models),
    ]
