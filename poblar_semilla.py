import os
import django

# Configurar el entorno de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from gestion_red.models import Router

def cargar_semilla():
    print("Iniciando carga del Router semilla...")
    
    # Crea únicamente el router principal. El demonio de topología (al llamarlo con PUT /topologia)
    # se encargará de descubrir el resto de routers y sus interfaces por CDP de forma automática.
    router_obj, created = Router.objects.get_or_create(
        hostname="Edge",
        defaults={
            "rol": "EDGE",
            "ip_administrativa": "192.168.100.1", # Cambia esto si la IP administrativa de tu router Edge es distinta
            "ip_loopback": "192.168.50.1",
            "empresa": "FI-UNAM",
            "sistema_operativo": "Cisco IOS"
        }
    )
    if created:
        print(f" -> Router Semilla '{router_obj.hostname}' ({router_obj.ip_administrativa}) creado con éxito.")
    else:
        print(f" -> El Router Semilla '{router_obj.hostname}' ya existía en la base de datos.")

if __name__ == "__main__":
    cargar_semilla()
    print("¡Base de datos lista para arrancar el demonio de descubrimiento!")
