"""
URL configuration for config project.

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
from django.urls import path
from gestion_red import views

urlpatterns = [
    path("admin/", admin.site.urls),
   # Usuarios Globales
    path('usuarios/', views.usuarios_globales, name='usuarios_globales'),
    
    # Enrutadores
    path('routers', views.lista_routers, name='lista_routers'),
    path('routers/<str:hostname>/', views.detalle_router, name='detalle_router'),
    
    # Interfaces e Usuarios por Enrutador
    path('routers/<str:hostname>/interfaces', views.interfaces_router, name='interfaces_router'),
    path('routers/<str:hostname>/usuarios/', views.usuarios_por_enrutador, name='usuarios_por_enrutador'),
    
    # Topología
    path('topologia', views.gestionar_topologia, name='gestionar_topologia'),
    path('topologia/grafica', views.grafica_topologia, name='grafica_topologia'),
    
    # Monitoreo y Trampas por Interfaz
    path('routers/<str:hostname>/interfaces/<str:interfaz>/octetos/<int:tiempo>', views.monitoreo_octetos, name='monitoreo_octetos'),
    path('routers/<str:hostname>/interfaces/<str:interfaz>/estado', views.gestion_traps, name='gestion_traps'),
    path('routers/<str:hostname>/interfaces/<str:interfaz>/grafica', views.grafica_monitoreo, name='grafica_monitoreo'),
]
