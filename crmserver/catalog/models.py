import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class Storefront(models.Model):
    organization = models.OneToOneField('accounts.Organization', on_delete=models.CASCADE,
                                        related_name='storefront')
    slug = models.SlugField('Адрес страницы', max_length=64, unique=True)
    logo = models.BinaryField(null=True, blank=True, editable=False)
    logo_digest = models.CharField(max_length=64, blank=True, editable=False)

    def get_absolute_url(self):
        return reverse('catalog:store', args=[self.slug])


class ProductType(models.Model):
    storefront = models.ForeignKey(Storefront, on_delete=models.CASCADE, related_name='types')
    name = models.CharField('Название типа', max_length=100)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['storefront', 'name'], name='catalog_unique_type')]

    def __str__(self):
        return self.name


class Attribute(models.Model):
    class Kind(models.TextChoices):
        TEXT = 'text', 'Текст'
        NUMBER = 'number', 'Число'
        CHOICE = 'choice', 'Выбор из списка'

    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE, related_name='attributes')
    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField('Характеристика', max_length=100)
    kind = models.CharField('Формат', max_length=10, choices=Kind.choices, default=Kind.TEXT)
    options = models.JSONField(default=list, blank=True)
    required = models.BooleanField('Обязательное поле', default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']

    @property
    def value_key(self):
        return 'a' + self.key.hex


class Product(models.Model):
    product_type = models.ForeignKey(ProductType, on_delete=models.PROTECT, related_name='products')
    name = models.CharField('Название', max_length=200)
    description = models.TextField('Описание', blank=True, max_length=10000)
    price = models.DecimalField('Цена, ₽', max_digits=12, decimal_places=2, null=True, blank=True,
                                validators=[MinValueValidator(0)])
    in_stock = models.BooleanField('В наличии', default=True)
    published = models.BooleanField('Показывать в каталоге', default=True)
    values = models.JSONField(default=dict, blank=True)
    photo = models.BinaryField(null=True, blank=True, editable=False)
    photo_digest = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def get_absolute_url(self):
        return reverse('catalog:product', args=[self.product_type.storefront.slug, self.pk])

    @property
    def specifications(self):
        return [(a.name, self.values[a.value_key]) for a in self.product_type.attributes.all()
                if a.value_key in self.values and self.values[a.value_key] != '']
