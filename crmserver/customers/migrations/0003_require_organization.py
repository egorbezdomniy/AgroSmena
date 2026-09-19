from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('customers', '0002_organization'), ('accounts', '0002_preserve_legacy_data')]
    operations = [
        migrations.AlterField(model_name='customer', name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    to='accounts.organization', verbose_name='Организация')),
    ]
