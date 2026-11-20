from django.urls import path
from django.views.generic import RedirectView, TemplateView

app_name = 'portfolio'

PAGE_ROUTES = (
    '',
    'atp/',
    'promtech/',
    'agro/',
    'agro/catalog/',
    'agro/products/dosing/',
    'agro/products/packing/',
    'erzhanshop/',
    'erzhanshop/availability/',
    'erzhanshop/sales/',
    'erzhanshop/notebooks/',
    'erzhanshop/notebooks/1/',
    'erzhanshop/notebooks/brand/Demo-1/',
    'erzhanshop/pens/',
    'erzhanshop/pens/2/',
    'erzhanshop/pens/brand/Demo-2/',
    'erzhanshop/markers/',
    'erzhanshop/markers/3/',
    'erzhanshop/markers/brand/Demo-3/',
    'erzhanshop/organizers/',
    'erzhanshop/organizers/4/',
    'erzhanshop/organizers/brand/Demo-4/',
)

urlpatterns = [
    path(
        route,
        TemplateView.as_view(template_name=f'web/portfolio/{route}index.html'),
        name=route.rstrip('/').replace('/', '-') or 'home',
    )
    for route in PAGE_ROUTES
]
urlpatterns.append(path(
    'test/',
    RedirectView.as_view(pattern_name='web:portfolio:erzhanshop', permanent=True),
    name='test',
))
