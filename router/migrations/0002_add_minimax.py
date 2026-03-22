from django.db import migrations


def add_minimax(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.get_or_create(
        model_name='MiniMaxAI/MiniMax-M2:novita',
        defaults={
            'provider': 'hf',
            'price_per_1k_input_tokens': 0.0003,
            'price_per_1k_output_tokens': 0.0009,
            'max_context_tokens': 1000000,
            'base_hallucination_rate': 0.015,
            'is_active': True,
        }
    )


def remove_minimax(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.filter(model_name='MiniMaxAI/MiniMax-M2:novita').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('router', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_minimax, remove_minimax),
    ]
