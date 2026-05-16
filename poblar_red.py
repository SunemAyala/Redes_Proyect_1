# poblar_red.py
import os
import django

# Configurar el entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from gestion_red.models import Router, Interfaz
from monitoreo.models import MonitoreoConfig, RegistroOcteto
from django.utils import timezone
import random

def cargar_topologia_base():
    print("Iniciando carga de la topología base...")

    # 1. Definición de los Routers según los roles y direccionamiento del PDF
    # Edge (.1), R1 (.2), R2 (.3), TORs (.4 en adelante)
    routers_datos = [
        {"hostname": "Edge", "rol": "EDGE", "ip_admin": "192.168.100.1", "ip_loopback": "192.168.50.1"},
        {"hostname": "R1", "rol": "CORE", "ip_admin": "192.168.100.2", "ip_loopback": "192.168.50.2"},
        {"hostname": "R2", "rol": "CORE", "ip_admin": "192.168.100.3", "ip_loopback": "192.168.50.3"},
        {"hostname": "TOR-1", "rol": "LEAF", "ip_admin": "192.168.100.4", "ip_loopback": "192.168.50.4"},
        {"hostname": "TOR-2", "rol": "LEAF", "ip_admin": "192.168.100.5", "ip_loopback": "192.168.50.5"},
    ]

    routers_creados = {}
    for r in routers_datos:
        router_obj, created = Router.objects.get_or_create(
            hostname=r["hostname"],
            defaults={
                "rol": r["rol"],
                "ip_administrativa": r["ip_admin"],
                "ip_loopback": r["ip_loopback"],
                "empresa": "FI-UNAM",
                "sistema_operativo": "Cisco IOS"
            }
        )
        routers_creados[r["hostname"]] = router_obj
        if created:
            print(f" -> Router {r['hostname']} creado con éxito.")

    # 2. Definición de algunas Interfaces críticas para pruebas (Formato f1_0)
    # Formato solicitado: f1_0 o fastethernet1_0
    interfaces_datos = [
        {"router": "Edge", "nombre": "f1_0", "ip": "10.0.0.1", "mask": "255.255.255.252"},
        {"router": "R1", "nombre": "f1_0", "ip": "10.0.0.2", "mask": "255.255.255.252"},
        {"router": "R1", "nombre": "f2_0", "ip": "192.168.0.1", "mask": "255.255.255.0"},
        {"router": "TOR-1", "nombre": "f1_0", "ip": "192.168.0.2", "mask": "255.255.255.0"},
    ]

    for i in interfaces_datos:
        interfaz_obj, created = Interfaz.objects.get_or_create(
            router=routers_creados[i["router"]],
            nombre=i["nombre"],
            defaults={
                "ip_address": i["ip"],
                "netmask": i["mask"],
                "estado": True
            }
        )
        if created:
            print(f"   -> Interfaz {i['nombre']} añadida a {i['router']}.")

    # 3. Enlazar un cable de prueba (Topología dinámica simulada)
    # Conectamos Edge f1_0 con R1 f1_0
    int_edge = Interfaz.objects.get(router__hostname="Edge", nombre="f1_0")
    int_r1 = Interfaz.objects.get(router__hostname="R1", nombre="f1_0")
    
    int_edge.conectado_a = int_r1
    int_edge.save()
    int_r1.conectado_a = int_edge
    int_r1.save()
    print(" -> Enlace Edge f1_0 <---> R1 f1_0 interconectado.")
    # 4. Configurar monitoreo de prueba y muestras
    print(" -> Configurando monitoreo de prueba...")
    for i in Interfaz.objects.all():
        m_config, _ = MonitoreoConfig.objects.get_or_create(
            interfaz=i,
            defaults={'monitoreo_octetos_activo': True, 'intervalo_muestreo': 10}
        )
        # Crear 10 muestras aleatorias para la gráfica
        base_val = random.randint(1000, 5000)
        for t in range(10):
            RegistroOcteto.objects.create(
                interfaz=i,
                octetos_entrada=base_val + (t * random.randint(100, 500)),
                timestamp=timezone.now()
            )
    print(" -> Datos de monitoreo generados.")

if __name__ == "__main__":
    cargar_topologia_base()
    print("¡Población completada con éxito!")
