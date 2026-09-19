from django.contrib.auth.views import LogoutView
from django.urls import path

from accounts import views

app_name = 'accounts'
urlpatterns = [
    path('login/', views.SignInView.as_view(), name='login'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('settings/users/', views.UsersView.as_view(), name='users'),
    path('settings/users/new/', views.AddUserView.as_view(), name='user-add'),
    path('settings/users/<int:pk>/role/', views.EditRoleView.as_view(), name='user-role'),
    path('settings/users/<int:pk>/remove/', views.RemoveUserView.as_view(), name='user-remove'),
]
