"""
URL configuration for crmserver project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from customers.views import CustomerViewSet
from deals.views import DealViewSet
from tasks.views import TaskViewSet
from crmserver.app_updates import AppUpdateView
from crmserver.installers import DownloadPageView, InstallerAdminView, InstallerDownloadView

router = DefaultRouter()
router.register('customers', CustomerViewSet)
router.register('deals', DealViewSet)
router.register('tasks', TaskViewSet)

urlpatterns = [
    path('download/', DownloadPageView.as_view(), name='download'),
    path('download/installer/', InstallerDownloadView.as_view(), name='installer-download'),
    path('release-admin/', InstallerAdminView.as_view(), name='installer-admin'),
    path('api/app/update/', AppUpdateView.as_view(), name='app-update'),
    path('api/sync/', include('synchronization.urls')),
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('', include('accounts.urls')),
    path('', include('web.urls')),
]
