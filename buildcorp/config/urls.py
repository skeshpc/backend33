from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "BuildCorp · Administración"
admin.site.site_title = "BuildCorp"
admin.site.index_title = "Gestión del pañol de herramientas"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("herramientas.api.urls")),
    path("cuenta/ingresar/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("cuenta/salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("herramientas.urls")),
]

handler403 = "herramientas.views.error_403"
handler404 = "herramientas.views.error_404"
handler500 = "herramientas.views.error_500"
