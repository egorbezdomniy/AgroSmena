from django.urls import path

from catalog import views

app_name = 'catalog'
urlpatterns = [
    path('manage/logo/', views.edit_logo, name='logo-edit'),
    path('manage/create/', views.create_store, name='create'),
    path('manage/types/new/', views.create_type, name='type-add'),
    path('manage/types/<int:pk>/delete/', views.delete_type, name='type-delete'),
    path('manage/products/new/', views.choose_type, name='choose-type'),
    path('manage/products/new/<int:type_pk>/', views.edit_product, name='product-add'),
    path('manage/products/<int:pk>/edit/', views.edit_product, name='product-edit'),
    path('manage/products/<int:pk>/delete/', views.delete_product, name='product-delete'),
    path('<slug:slug>/', views.store, name='store'),
    path('<slug:slug>/logo/', views.logo, name='logo'),
    path('<slug:slug>/<int:pk>/', views.product, name='product'),
    path('<slug:slug>/<int:pk>/photo/', views.photo, name='photo'),
]
