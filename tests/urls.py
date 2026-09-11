from django.urls import include, path

urlpatterns = [
    path('admin/', __import__('django.contrib.admin', fromlist=['site']).site.urls),
    path('', include('trusts.urls')),
]
