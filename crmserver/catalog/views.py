import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.access import membership_for
from accounts.models import Membership, Organization
from catalog.forms import AttributeForms, FilterForm, LogoForm, ProductForm, StorefrontForm, TypeForm
from catalog.models import Attribute, Product, ProductType, Storefront
from catalog.presets import create_presets


def admin_membership(request):
    membership = membership_for(request.user)
    if not membership or membership.role != Membership.Role.ADMIN:
        raise PermissionDenied('Управлять каталогом может только администратор организации.')
    return membership


def admin_store(request):
    membership = admin_membership(request)
    return get_object_or_404(Storefront.objects.defer('logo').select_related('organization'), organization=membership.organization)


def owns_store(request, storefront):
    membership = membership_for(request.user)
    return bool(membership and membership.organization_id == storefront.organization_id
                and membership.role == Membership.Role.ADMIN)


def products_for(storefront, can_manage=False):
    products = Product.objects.filter(product_type__storefront=storefront).select_related(
        'product_type__storefront').prefetch_related('product_type__attributes').defer('photo', 'product_type__storefront__logo')
    return products if can_manage else products.filter(published=True)


@login_required
@require_http_methods(['GET', 'POST'])
def create_store(request):
    membership = admin_membership(request)
    existing = Storefront.objects.defer('logo').filter(organization=membership.organization).first()
    if existing:
        return redirect(existing)
    form = StorefrontForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=membership.organization_id)
                existing = Storefront.objects.defer('logo').filter(organization=membership.organization).first()
                if existing:
                    return redirect(existing)
                storefront = form.save(commit=False)
                storefront.organization = membership.organization
                storefront.save()
                create_presets(storefront)
        except IntegrityError:
            form.add_error('slug', 'Адрес уже занят. Выберите другой.')
        else:
            messages.success(request, 'Каталог создан. Добавьте первый товар — он появится по вашей ссылке.')
            return redirect(storefront)
    return render(request, 'catalog/create.html', {'form': form, 'section': 'catalog'})


@require_GET
def store(request, slug):
    storefront = get_object_or_404(Storefront.objects.defer('logo').select_related('organization'), slug=slug)
    can_manage = owns_store(request, storefront)
    products = products_for(storefront, can_manage)
    form = FilterForm(request.GET, storefront=storefront)
    if form.is_valid():
        data = form.cleaned_data
        if data['q']:
            products = products.filter(Q(name__icontains=data['q']) | Q(description__icontains=data['q']))
        if data['type']:
            products = products.filter(product_type=data['type'])
        for field, lookup in [('price_min', 'price__gte'), ('price_max', 'price__lte')]:
            if data[field] is not None:
                products = products.filter(**{lookup: data[field]})
        if data['in_stock']:
            products = products.filter(in_stock=True)
        for attribute in form.attributes:
            key = 'attr_' + attribute.value_key
            lookup = 'values__' + attribute.value_key
            if attribute.kind == Attribute.Kind.NUMBER:
                for suffix, op in [('min', 'gte'), ('max', 'lte')]:
                    value = data.get(key + '_' + suffix)
                    if value is not None:
                        products = products.filter(**{lookup + '__' + op: float(value)})
            elif data.get(key):
                products = products.filter(**{lookup + ('__icontains' if attribute.kind == Attribute.Kind.TEXT else ''): data[key]})
        ordering = data['sort']
        if ordering in ('price', '-price'):
            expression = F('price').asc(nulls_last=True) if ordering == 'price' else F('price').desc(nulls_last=True)
            products = products.order_by(expression, '-pk')
        elif ordering == 'name':
            products = products.order_by('name', 'pk')
    else:
        products = products.none()
    page = Paginator(products, 12).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'catalog/store.html', {
        'storefront': storefront, 'can_manage': can_manage, 'form': form, 'page_obj': page,
        'query_string': params.urlencode(), 'types': storefront.types.all(),
    })


@require_GET
def product(request, slug, pk):
    storefront = get_object_or_404(Storefront.objects.defer('logo').select_related('organization'), slug=slug)
    can_manage = owns_store(request, storefront)
    item = get_object_or_404(products_for(storefront, can_manage), pk=pk)
    related = products_for(storefront).filter(product_type=item.product_type).exclude(pk=pk)[:3]
    return render(request, 'catalog/product.html', {'storefront': storefront, 'product': item,
                   'can_manage': can_manage, 'related': related})


@require_GET
def photo(request, slug, pk):
    storefront = get_object_or_404(Storefront.objects.defer('logo'), slug=slug)
    item = get_object_or_404(products_for(storefront, owns_store(request, storefront)), pk=pk)
    if not item.photo_digest:
        raise Http404
    etag = '"' + item.photo_digest + '"'
    response = (HttpResponseNotModified() if request.headers.get('If-None-Match') == etag else
                HttpResponse(bytes(item.photo), content_type='image/jpeg'))
    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
def edit_logo(request):
    storefront = admin_store(request)
    form = LogoForm(request.POST if request.method == 'POST' else None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        storefront.logo = form.cleaned_data['logo']
        storefront.logo_digest = hashlib.sha256(storefront.logo).hexdigest()
        storefront.save(update_fields=['logo', 'logo_digest'])
        messages.success(request, 'Логотип обновлён.')
        return redirect(storefront)
    return render(request, 'catalog/logo_form.html', {'storefront': storefront, 'can_manage': True, 'form': form})


@require_GET
def logo(request, slug):
    storefront = get_object_or_404(Storefront.objects.defer('logo'), slug=slug)
    if not storefront.logo_digest:
        raise Http404
    etag = '"' + storefront.logo_digest + '"'
    response = (HttpResponseNotModified() if request.headers.get('If-None-Match') == etag else
                HttpResponse(bytes(storefront.logo), content_type='image/png'))
    response['ETag'] = etag
    response['Cache-Control'] = 'public, no-cache'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
def create_type(request):
    storefront = admin_store(request)
    form = TypeForm(request.POST if request.method == 'POST' else None, storefront=storefront)
    attributes = AttributeForms(request.POST if request.method == 'POST' else None, prefix='attributes')
    if request.method == 'POST':
        valid = form.is_valid()
        valid_attributes = attributes.is_valid()
        if valid and valid_attributes:
            try:
                with transaction.atomic():
                    product_type = form.save()
                    for i, attribute in enumerate(attributes):
                        data = attribute.cleaned_data
                        if data and not data.get('DELETE'):
                            Attribute.objects.create(product_type=product_type, position=i,
                                **{k: data[k] for k in ('name', 'kind', 'options', 'required')})
            except IntegrityError:
                form.add_error('name', 'Тип с таким названием уже существует.')
            else:
                messages.success(request, 'Тип товара создан.')
                return redirect('catalog:product-add', type_pk=product_type.pk)
    return render(request, 'catalog/type_form.html', {'storefront': storefront, 'can_manage': True,
                  'form': form, 'attributes': attributes})


@login_required
@require_GET
def choose_type(request):
    storefront = admin_store(request)
    return render(request, 'catalog/choose_type.html', {'storefront': storefront, 'can_manage': True,
                  'types': storefront.types.prefetch_related('attributes')})


@login_required
@require_http_methods(['GET', 'POST'])
def delete_type(request, pk):
    storefront = admin_store(request)
    product_type = get_object_or_404(ProductType, pk=pk, storefront=storefront)
    if request.method == 'POST':
        try:
            product_type.delete()
        except ProtectedError:
            messages.error(request, 'Нельзя удалить тип, пока к нему привязаны товары, включая черновики. Сначала удалите эти товары.')
        else:
            messages.success(request, 'Тип товара удалён.')
            return redirect('catalog:choose-type')
    return render(request, 'catalog/type_delete.html', {
        'storefront': storefront, 'can_manage': True, 'product_type': product_type,
        'product_count': product_type.products.count(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def edit_product(request, type_pk=None, pk=None):
    storefront = admin_store(request)
    item = get_object_or_404(products_for(storefront, True), pk=pk) if pk is not None else None
    product_type = item.product_type if item else get_object_or_404(ProductType, pk=type_pk, storefront=storefront)
    form = ProductForm(request.POST if request.method == 'POST' else None, request.FILES or None,
                       instance=item, product_type=product_type)
    if request.method == 'POST' and form.is_valid():
        item = form.save()
        messages.success(request, 'Товар сохранён.' if item.published else 'Черновик сохранён. Пока его видят только администраторы.')
        return redirect(item)
    return render(request, 'catalog/product_form.html', {'storefront': storefront, 'can_manage': True,
                  'form': form, 'product': item, 'product_type': product_type})


@login_required
@require_http_methods(['GET', 'POST'])
def delete_product(request, pk):
    storefront = admin_store(request)
    item = get_object_or_404(products_for(storefront, True), pk=pk)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Товар удалён.')
        return redirect(storefront)
    return render(request, 'catalog/delete.html', {'storefront': storefront, 'product': item, 'can_manage': True})
