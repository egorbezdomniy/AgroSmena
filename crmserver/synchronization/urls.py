from django.urls import path
from .views import ExchangeView, LoginView

urlpatterns = [path('login/', LoginView.as_view()), path('exchange/', ExchangeView.as_view())]
