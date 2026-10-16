import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0002_preserve_legacy_data')]
    operations = [
        migrations.CreateModel(name='Storefront', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('slug', models.SlugField(max_length=64, unique=True, verbose_name='Адрес страницы')),
            ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                related_name='storefront', to='accounts.organization')),
        ]),
        migrations.CreateModel(name='ProductType', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=100, verbose_name='Название типа')),
            ('storefront', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name='types', to='catalog.storefront')),
        ], options={'ordering': ['name', 'pk']}),
        migrations.AddConstraint(model_name='producttype', constraint=models.UniqueConstraint(
            fields=('storefront', 'name'), name='catalog_unique_type')),
        migrations.CreateModel(name='Attribute', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('key', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ('name', models.CharField(max_length=100, verbose_name='Характеристика')),
            ('kind', models.CharField(choices=[('text', 'Текст'), ('number', 'Число'), ('choice', 'Выбор из списка')],
                default='text', max_length=10, verbose_name='Формат')),
            ('options', models.JSONField(blank=True, default=list)),
            ('required', models.BooleanField(default=False, verbose_name='Обязательное поле')),
            ('position', models.PositiveIntegerField(default=0)),
            ('product_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name='attributes', to='catalog.producttype')),
        ], options={'ordering': ['position', 'pk']}),
        migrations.CreateModel(name='Product', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('name', models.CharField(max_length=200, verbose_name='Название')),
            ('description', models.TextField(blank=True, max_length=10000, verbose_name='Описание')),
            ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True,
                validators=[django.core.validators.MinValueValidator(0)], verbose_name='Цена, ₽')),
            ('in_stock', models.BooleanField(default=True, verbose_name='В наличии')),
            ('published', models.BooleanField(default=True, verbose_name='Показывать в каталоге')),
            ('values', models.JSONField(blank=True, default=dict)),
            ('photo', models.BinaryField(blank=True, editable=False, null=True)),
            ('photo_digest', models.CharField(blank=True, editable=False, max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('product_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name='products', to='catalog.producttype')),
        ], options={'ordering': ['-created_at', '-pk']}),
    ]
