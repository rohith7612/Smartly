from django.db import migrations, models


def flag_judge_model(apps, schema_editor):
    ModelProfile = apps.get_model('router', 'ModelProfile')
    ModelProfile.objects.filter(model_name='MiniMaxAI/MiniMax-M2:novita').update(is_judge_model=True)


class Migration(migrations.Migration):

    dependencies = [
        ('router', '0003_swap_gemini'),
    ]

    operations = [
        migrations.AddField(
            model_name='modelprofile',
            name='is_judge_model',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(flag_judge_model, migrations.RunPython.noop),
    ]
