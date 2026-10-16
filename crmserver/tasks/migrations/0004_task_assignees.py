from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tasks', '0003_require_organization'), ('accounts', '0002_preserve_legacy_data')]
    operations = [
        migrations.AddField(
            model_name='task', name='assignees',
            field=models.ManyToManyField(blank=True, related_name='assigned_tasks',
                                         to='accounts.membership', verbose_name='Сотрудники'),
        ),
    ]
