from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalog', '0001_initial')]
    operations = [
        migrations.AddField(model_name='storefront', name='logo',
                            field=models.BinaryField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name='storefront', name='logo_digest',
                            field=models.CharField(blank=True, editable=False, max_length=64)),
    ]
