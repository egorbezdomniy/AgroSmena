import hashlib
import warnings
from io import BytesIO

from django import forms
from django.forms import BaseFormSet, formset_factory
from PIL import Image, ImageOps, UnidentifiedImageError

from catalog.models import Attribute, Product, ProductType, Storefront


class StorefrontForm(forms.ModelForm):
    class Meta:
        model = Storefront
        fields = ['slug']
        help_texts = {'slug': 'От 3 до 64 символов: латинские буквы, цифры и дефис. Например, zeleny-sad.'}
        widgets = {'slug': forms.TextInput(attrs={'placeholder': 'zeleny-sad', 'autocapitalize': 'none'})}

    def clean_slug(self):
        slug = self.cleaned_data['slug'].lower()
        if len(slug) < 3 or slug == 'manage' or '_' in slug or slug.startswith('-') or slug.endswith('-'):
            raise forms.ValidationError('Укажите адрес из латинских букв, цифр и дефисов, не короче 3 символов.')
        if Storefront.objects.filter(slug=slug).exists():
            raise forms.ValidationError('Этот адрес уже занят. Выберите другой.')
        return slug


class LogoForm(forms.Form):
    logo = forms.FileField(label='Логотип организации',
        help_text='PNG, JPEG или WebP до 5 МБ. Прозрачный фон PNG сохранится.',
        widget=forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}))

    def clean_logo(self):
        upload = self.cleaned_data['logo']
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Размер логотипа должен быть не больше 5 МБ.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(upload) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 25000000:
                        raise ValueError
                    picture = ImageOps.exif_transpose(source)
                    picture.thumbnail((512, 512))
                    output = BytesIO()
                    picture.convert('RGBA').save(output, format='PNG', optimize=True)
                    return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise forms.ValidationError('Выберите корректное изображение PNG, JPEG или WebP до 25 мегапикселей.')


class TypeForm(forms.ModelForm):
    class Meta:
        model = ProductType
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'Например, комнатные растения'})}

    def __init__(self, *args, storefront, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.storefront = storefront


class AttributeForm(forms.Form):
    name = forms.CharField(label='Характеристика', max_length=100,
                           widget=forms.TextInput(attrs={'placeholder': 'Например, цвет'}))
    kind = forms.ChoiceField(label='Формат', choices=Attribute.Kind.choices, initial=Attribute.Kind.TEXT)
    options = forms.CharField(label='Варианты', required=False, max_length=4000,
                              help_text='Для списка — один вариант в строке.',
                              widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Белый\nРозовый\nКрасный'}))
    required = forms.BooleanField(label='Обязательно', required=False)

    def clean(self):
        data = super().clean()
        options = list(dict.fromkeys(x.strip() for x in data.get('options', '').splitlines() if x.strip()))
        if data.get('kind') == Attribute.Kind.CHOICE:
            if not options or len(options) > 50 or any(len(x) > 100 for x in options):
                self.add_error('options', 'Добавьте от 1 до 50 вариантов, каждый не длиннее 100 символов.')
        else:
            options = []
        data['options'] = options
        return data


class AttributeFormSet(BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        names = [f.cleaned_data['name'].casefold() for f in self.forms
                 if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if len(set(names)) != len(names):
            raise forms.ValidationError('Названия характеристик не должны повторяться.')


AttributeForms = formset_factory(AttributeForm, formset=AttributeFormSet, extra=1,
                                 can_delete=True, max_num=20, validate_max=True, absolute_max=20)


class ProductForm(forms.ModelForm):
    image = forms.FileField(label='Фотография', required=False,
                            help_text='JPEG, PNG или WebP, до 5 МБ.',
                            widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))
    remove_image = forms.BooleanField(label='Удалить фотографию', required=False)

    class Meta:
        model = Product
        fields = ['name', 'description', 'price', 'in_stock', 'published']
        widgets = {'description': forms.Textarea(attrs={'rows': 4}),
                   'price': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'По запросу'})}

    def __init__(self, *args, product_type, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.product_type = product_type
        self.attributes = list(product_type.attributes.all())
        if not self.instance.photo_digest:
            self.fields.pop('remove_image')
        for attribute in self.attributes:
            options = {'label': attribute.name, 'required': attribute.required,
                       'initial': self.instance.values.get(attribute.value_key)}
            if attribute.kind == Attribute.Kind.CHOICE:
                field = forms.ChoiceField(choices=[('', 'Выберите значение')] + [(x, x) for x in attribute.options], **options)
            elif attribute.kind == Attribute.Kind.NUMBER:
                field = forms.DecimalField(max_digits=12, decimal_places=2, **options)
            else:
                field = forms.CharField(max_length=300, **options)
            self.fields['attr_' + attribute.value_key] = field

    def clean_image(self):
        upload = self.cleaned_data.get('image')
        if not upload:
            return None
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Размер фотографии должен быть не больше 5 МБ.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(upload) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 25000000:
                        raise ValueError
                    picture = ImageOps.exif_transpose(source)
                    picture.thumbnail((1600, 1600))
                    rgba = picture.convert('RGBA')
                    background = Image.new('RGB', rgba.size, '#f3f5ed')
                    background.paste(rgba, mask=rgba.getchannel('A'))
                    output = BytesIO()
                    background.save(output, format='JPEG', quality=85, optimize=True)
                    return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise forms.ValidationError('Не удалось прочитать фото. Выберите JPEG, PNG или WebP до 25 мегапикселей.')

    def save(self, commit=True):
        product = super().save(commit=False)
        product.values = {}
        for attribute in self.attributes:
            value = self.cleaned_data.get('attr_' + attribute.value_key)
            if value not in (None, ''):
                product.values[attribute.value_key] = float(value) if attribute.kind == Attribute.Kind.NUMBER else value
        image = self.cleaned_data.get('image')
        if image:
            product.photo = image
            product.photo_digest = hashlib.sha256(image).hexdigest()
        elif self.cleaned_data.get('remove_image'):
            product.photo = None
            product.photo_digest = ''
        if commit:
            product.save()
        return product


class FilterForm(forms.Form):
    q = forms.CharField(label='Поиск', required=False, max_length=200,
                        widget=forms.TextInput(attrs={'placeholder': 'Название или описание', 'type': 'search'}))
    type = forms.ModelChoiceField(label='Тип товара', queryset=ProductType.objects.none(), required=False,
                                  empty_label='Все товары')
    price_min = forms.DecimalField(label='Цена от, ₽', required=False, min_value=0, max_digits=12, decimal_places=2)
    price_max = forms.DecimalField(label='Цена до, ₽', required=False, min_value=0, max_digits=12, decimal_places=2)
    in_stock = forms.BooleanField(label='Только в наличии', required=False)
    sort = forms.ChoiceField(label='Порядок', required=False, choices=[('', 'Сначала новые'),
                            ('price', 'Цена по возрастанию'), ('-price', 'Цена по убыванию'), ('name', 'По названию')])

    def __init__(self, *args, storefront, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['type'].queryset = storefront.types.all()
        raw_type = self.data.get('type', '')
        self.selected_type = storefront.types.filter(pk=int(raw_type)).first() if raw_type.isascii() and raw_type.isdigit() and len(raw_type) < 10 else None
        self.attributes = list(self.selected_type.attributes.all()) if self.selected_type else []
        for attribute in self.attributes:
            key = 'attr_' + attribute.value_key
            if attribute.kind == Attribute.Kind.NUMBER:
                for suffix, label in [('min', 'от'), ('max', 'до')]:
                    self.fields[f'{key}_{suffix}'] = forms.DecimalField(label=f'{attribute.name} — {label}',
                        required=False, max_digits=12, decimal_places=2)
            elif attribute.kind == Attribute.Kind.CHOICE:
                self.fields[key] = forms.ChoiceField(label=attribute.name, required=False,
                    choices=[('', 'Любое значение')] + [(x, x) for x in attribute.options])
            else:
                self.fields[key] = forms.CharField(label=attribute.name, required=False, max_length=300)

    def clean(self):
        data = super().clean()
        for low, high in [('price_min', 'price_max')] + [
                (f'attr_{a.value_key}_min', f'attr_{a.value_key}_max')
                for a in self.attributes if a.kind == Attribute.Kind.NUMBER]:
            if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
                self.add_error(high, 'Верхняя граница должна быть не меньше нижней.')
        return data
