from django.conf.urls import url, include
from rest_framework import routers
from . import views

router = routers.DefaultRouter()
router.register(r'preorders', views.PreorderViewSet)
router.register(r'preorderpositions', views.PreorderPositionViewSet)

urlpatterns = [
    url(r'', include(router.urls, namespace='api'))
]