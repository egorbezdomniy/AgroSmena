from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('tasks', '0001_initial'), ('accounts', '0001_initial')]
    operations = [
        migrations.AddField(model_name='task', name='organization',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    to='accounts.organization', verbose_name='Организация')),
    ]
