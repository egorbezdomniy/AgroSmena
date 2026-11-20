from django.urls import include, path
from web import views

app_name = 'web'
urlpatterns = [
    path('', views.LandingView.as_view(), name='landing'),
    path('portfolio/', include('web.portfolio_urls')),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('customers/', views.CustomerListView.as_view(), name='customers'),
    path('customers/new/', views.CustomerCreateView.as_view(), name='customer-create'),
    path('customers/<int:pk>/', views.CustomerDetailView.as_view(), name='customer-detail'),
    path('customers/<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='customer-edit'),
    path('customers/<int:pk>/delete/', views.CustomerDeleteView.as_view(), name='customer-delete'),
    path('deals/', views.DealListView.as_view(), name='deals'),
    path('deals/new/', views.DealCreateView.as_view(), name='deal-create'),
    path('deals/<int:pk>/', views.DealDetailView.as_view(), name='deal-detail'),
    path('deals/<int:pk>/edit/', views.DealUpdateView.as_view(), name='deal-edit'),
    path('deals/<int:pk>/stage/', views.DealStageView.as_view(), name='deal-stage'),
    path('deals/<int:pk>/delete/', views.DealDeleteView.as_view(), name='deal-delete'),
    path('tasks/', views.TaskListView.as_view(), name='tasks'),
    path('tasks/new/', views.TaskCreateView.as_view(), name='task-create'),
    path('tasks/<int:pk>/', views.TaskDetailView.as_view(), name='task-detail'),
    path('tasks/<int:pk>/edit/', views.TaskUpdateView.as_view(), name='task-edit'),
    path('tasks/<int:pk>/status/', views.TaskStatusView.as_view(), name='task-status'),
    path('tasks/<int:pk>/delete/', views.TaskDeleteView.as_view(), name='task-delete'),
]
