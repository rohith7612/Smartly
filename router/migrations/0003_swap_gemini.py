from django.db import migrations


def swap_gemini(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.filter(model_name='gemini-2.0-flash').update(is_active=False)
    ModelProfile.objects.get_or_create(
        model_name='models/gemini-2.5-flash',
        defaults={
            'provider': 'google',
            'price_per_1k_input_tokens': 0.0001,
            'price_per_1k_output_tokens': 0.0004,
            'max_context_tokens': 1000000,
            'base_hallucination_rate': 0.02,
            'is_active': True,
        }
    )


def reverse_swap_gemini(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.filter(model_name='gemini-2.0-flash').update(is_active=True)
    ModelProfile.objects.filter(model_name='models/gemini-2.5-flash').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('router', '0002_add_minimax'),
    ]

    operations = [
        migrations.RunPython(swap_gemini, reverse_swap_gemini),
    ]
