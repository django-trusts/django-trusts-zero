from django.urls import path

urlpatterns = [
    path('admin/', __import__('django.contrib.admin', fromlist=['site']).site.urls),
]
