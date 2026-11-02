from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categorias", views.CategoriaViewSet)
router.register("obras", views.ObraViewSet)
router.register("contratistas", views.ContratistaViewSet)
router.register("herramientas", views.HerramientaViewSet)
router.register("prestamos", views.PrestamoViewSet)
router.register("planes", views.PlanViewSet)
router.register("ordenes", views.OrdenViewSet)
router.register("alertas", views.AlertaViewSet)

urlpatterns = [
    path("auth/token/", views.TokenView.as_view(), name="api_token"),
    path("resumen/", views.resumen, name="api_resumen"),
    path("sesion/", include("rest_framework.urls")),
    path("", include(router.urls)),
]
