from django.urls import path
from .views import ExchangeView, LoginView

urlpatterns = [path('login/', LoginView.as_view(), name='sync-login'),
               path('exchange/', ExchangeView.as_view(), name='sync-exchange')]
