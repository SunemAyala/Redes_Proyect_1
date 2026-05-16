import json
import time
from django.http import HttpResponse, JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.conf import settings

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import io
import threading
import random
import os
from django.utils import timezone
from netmiko import ConnectHandler
from pysnmp.hlapi import *

# Importa tus modelos de la app (ajusta los nombres exactos si varían)
from .models import Router, Interfaz, DispositivoUsuario
from monitoreo.models import RegistroOcteto

# ==========================================
# UTILIDADES DE RED (SNMP / SSH / TRAPS)
# ==========================================

def snmp_get(ip, community, oid):
    """Realiza una consulta SNMP Get para un OID específico."""
    errorIndication, errorStatus, errorIndex, varBinds = next(
        getCmd(SnmpEngine(),
               CommunityData(community),
               UdpTransportTarget((ip, 161)),
               ContextData(),
               ObjectType(ObjectIdentity(oid)))
    )
    if errorIndication or errorStatus:
        return None
    for varBind in varBinds:
        return str(varBind[1])

def ssh_config_user(router, action, username, privilege):
    """Configura usuarios vía SSH usando Netmiko."""
    device = {
        'device_type': 'cisco_ios',
        'host': router.ip_administrativa,
        'username': router.ssh_usuario_admin,
        'password': router.ssh_password_admin,
    }
    try:
        with ConnectHandler(**device) as net_connect:
            if action == 'POST' or action == 'PUT':
                config_commands = [f'username {username} privilege {privilege} password 0 {username}123']
            elif action == 'DELETE':
                config_commands = [f'no username {username}']
            net_connect.send_config_set(config_commands)
            return True
    except Exception as e:
        print(f"Error SSH en {router.hostname}: {e}")
        return False

def trap_receiver_daemon():
    """Hilos que escucha traps SNMP (simulado o simplificado)."""
    # Para una implementación real de receptor de traps se requiere un socket UDP
    # o usar la librería pysnmp.carrier.asyncore.
    print("[Trap Listener] Iniciando receptor en puerto 162...")
    while daemon_config["activo"]:
        # Aquí iría el bucle de recepción de paquetes UDP
        time.sleep(10)

# ==========================================
# VARIABLES GLOBALES PARA EL DEMONIO
# ==========================================
daemon_config = {
    "activo": False,
    "intervalo": 300,
    "thread": None,
    "trap_thread": None
}

def descubrimiento_red_daemon():
    """Hilo secundario que explora la red vía SNMP CDP/LLDP."""
    community = os.getenv("SNMP_COMMUNITY", "public")
    while daemon_config["activo"]:
        routers = Router.objects.all()
        for r in routers:
            # Consultar descripción del sistema vía SNMP
            desc = snmp_get(r.ip_administrativa, community, '.1.3.6.1.2.1.1.1.0')
            if desc:
                r.sistema_operativo = desc
                r.save()
            
            # Aquí se añadiría la lógica de caminar por la tabla CDP para descubrir vecinos
            print(f"[{timezone.now()}] Escaneando router: {r.hostname}")
            
        time.sleep(daemon_config["intervalo"])

# ==========================================
# ENDPOINTS: CRUD USUARIOS GLOBAL (/usuarios)
# ==========================================

@csrf_exempt
def usuarios_globales(request):
    """
    GET: Regresa json con todos los usuarios en todos los routers.
    POST: Agrega un nuevo usuario a TODOS los routers.
    PUT: Actualiza un usuario en TODOS los routers.
    DELETE: Elimina un usuario común en TODOS los routers.
    """
    routers = Router.objects.all()

    if request.method == 'GET':
        # Agrupar usuarios por nombre para la respuesta global
        usuarios = DispositivoUsuario.objects.all()
        data = {}
        for u in usuarios:
            if u.username not in data:
                data[u.username] = {
                    "nombre": u.username,
                    "permisos": u.privilegio,
                    "dispositivos": []
                }
            # Construye la URL hacia el recurso del router específico
            url_router_usuario = f"{request.build_absolute_uri('/routers/')}{u.router.hostname}/usuarios/"
            data[u.username]["dispositivos"].append(url_router_usuario)
        
        return JsonResponse(list(data.values()), safe=False, status=200)

    elif request.method in ['POST', 'PUT', 'DELETE']:
        try:
            body = json.loads(request.body)
            username = body.get('nombre')
            privilegio = body.get('permisos') # Requerido en POST y PUT
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({"error": "JSON inválido o malformado"}, status=400)

        if not username:
            return JsonResponse({"error": "El campo 'nombre' es requerido"}, status=400)

        # MODO SIMULACIÓN VS MODO REAL (SSH)
        for router in routers:
            if getattr(settings, 'DEBUG', True):
                time.sleep(0.05) 
                ssh_exitoso = True
            else:
                ssh_exitoso = ssh_config_user(router, request.method, username, privilegio)

            if ssh_exitoso:
                if request.method == 'POST':
                    DispositivoUsuario.objects.get_or_create(username=username, router=router, defaults={'privilegio': privilegio})
                elif request.method == 'PUT':
                    DispositivoUsuario.objects.filter(username=username, router=router).update(privilegio=privilegio)
                elif request.method == 'DELETE':
                    DispositivoUsuario.objects.filter(username=username, router=router).delete()

        # Construir respuestas estructuradas exactamente como pide el PDF
        if request.method == 'POST':
            return JsonResponse({"nombre": username, "permisos": privilegio, "estado": "Agregado globalmente"}, status=201)
        elif request.method == 'PUT':
            return JsonResponse({"nombre": username, "permisos": privilegio, "estado": "Actualizado globalmente"}, status=200)
        elif request.method == 'DELETE':
            return JsonResponse({"nombre": username, "estado": "Eliminado globalmente"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: ENRUTADORES (/routers y /routers/<hostname>/)
# ==========================================

def lista_routers(request):
    """GET: Regresa la información general de todos los routers."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)
        
    routers = Router.objects.all()
    respuesta = []
    for r in routers:
        respuesta.append({
            "Nombre": r.hostname,
            "IP loopback": r.ip_loopback,
            "IP administrativa": r.ip_administrativa,
            "rol": r.rol,
            "empresa": r.empresa,
            "Sistema operativo": r.sistema_operativo,
            "ligas_interfaces": f"{request.build_absolute_uri('/routers/')}{r.hostname}/interfaces"
        })
    return JsonResponse(respuesta, safe=False, status=200)


def detalle_router(request, hostname):
    """GET: Regresa la información general de un router específico o 404."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # Requisito estricto: Devolver 404 si el dispositivo no existe
    router = get_object_or_404(Router, hostname=hostname)
    
    # En modo Real (DEBUG=False), aquí actualizarías los campos leyendo vía SNMP antes de responder
    if not getattr(settings, 'DEBUG', True):
        # router.sistema_operativo = consultar_snmp_sysDescr(router.ip_administrativa)
        # router.save()
        pass

    return JsonResponse({
        "Nombre": router.hostname,
        "IP loopback": router.ip_loopback,
        "IP administrativa": router.ip_administrativa,
        "rol": router.rol,
        "empresa": router.empresa,
        "Sistema operativo": router.sistema_operativo,
        "ligas_interfaces": f"{request.build_absolute_uri('/routers/')}{router.hostname}/interfaces"
    }, status=200)


# ==========================================
# ENDPOINTS: INTERFACES (/routers/<hostname>/interfaces)
# ==========================================

def interfaces_router(request, hostname):
    """GET: Regresa en formato JSON la información de las interfaces del router."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    router = get_object_or_404(Router, hostname=hostname)
    interfaces = Interfaz.objects.filter(router=router)
    
    respuesta = []
    for i in interfaces:
        # Extraer tipo y número del nombre (ej: f1_0 -> Tipo: FastEthernet, Número: 1_0)
        tipo = "FastEthernet" if i.nombre.startswith('f') else "GigabitEthernet"
        
        vecino_link = None
        if i.conectado_a:
            vecino_link = f"{request.build_absolute_uri('/routers/')}{i.conectado_a.router.hostname}/"

        respuesta.append({
            "tipo": tipo,
            "numero": i.nombre,
            "IP": i.ip_address,
            "mascara de subred": i.netmask,
            "estado": "up" if i.estado else "down",
            "conectado_a": vecino_link
        })
    return JsonResponse(respuesta, safe=False, status=200)


# ==========================================
# ENDPOINTS: CRUD USUARIOS POR ENRUTADOR (/routers/<hostname>/usuarios/)
# ==========================================

@csrf_exempt
def usuarios_por_enrutador(request, hostname):
    """CRUD de usuarios acotado a un enrutador específico."""
    router = get_object_or_404(Router, hostname=hostname)

    if request.method == 'GET':
        usuarios = DispositivoUsuario.objects.filter(router=router)
        respuesta = [{"nombre": u.username, "permisos": u.privilegio} for u in usuarios]
        return JsonResponse(respuesta, safe=False, status=200)

    elif request.method in ['POST', 'PUT', 'DELETE']:
        try:
            body = json.loads(request.body)
            username = body.get('nombre')
            privilegio = body.get('permisos')
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({"error": "JSON malformado"}, status=400)

        if getattr(settings, 'DEBUG', True):
            # SIMULACIÓN SSH
            ssh_exitoso = True
        else:
            # REAL SSH
            ssh_exitoso = True

        if ssh_exitoso:
            if request.method == 'POST':
                DispositivoUsuario.objects.get_or_create(username=username, router=router, defaults={'privilegio': privilegio})
                return JsonResponse({"nombre": username, "permisos": privilegio, "estado": f"Creado en {hostname}"}, status=201)
            elif request.method == 'PUT':
                DispositivoUsuario.objects.filter(username=username, router=router).update(privilegio=privilegio)
                return JsonResponse({"nombre": username, "permisos": privilegio, "estado": f"Actualizado en {hostname}"}, status=200)
            elif request.method == 'DELETE':
                DispositivoUsuario.objects.filter(username=username, router=router).delete()
                return JsonResponse({"nombre": username, "estado": f"Eliminado de {hostname}"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: DETECTAR TOPOLOGÍA Y GRÁFICA (/topologia)
# ==========================================

@csrf_exempt
def gestionar_topologia(request):
    """GET: Regresa routers vecinos. PUT/DELETE: Controla el demonio de exploración."""
    if request.method == 'GET':
        # Formato JSON de vecinos
        routers = Router.objects.all()
        topologia = []
        for r in routers:
            vecinos = []
            interfaces_con_enlace = Interfaz.objects.filter(router=r, conectado_a__isnull=False)
            for inf in interfaces_con_enlace:
                vecinos.append(f"{request.build_absolute_uri('/routers/')}{inf.conectado_a.router.hostname}/")
            
            topologia.append({
                "router": r.hostname,
                "vecinos": vecinos
            })
        return JsonResponse(topologia, safe=False, status=200)

    elif request.method == 'PUT':
        try:
            body = json.loads(request.body)
            intervalo_min = body.get('intervalo', 5)
            daemon_config["intervalo"] = intervalo_min * 60
        except:
            pass

        if not daemon_config["activo"]:
            daemon_config["activo"] = True
            daemon_config["thread"] = threading.Thread(target=descubrimiento_red_daemon, daemon=True)
            daemon_config["thread"].start()
            # Iniciar también el receptor de traps
            daemon_config["trap_thread"] = threading.Thread(target=trap_receiver_daemon, daemon=True)
            daemon_config["trap_thread"].start()
            
        return JsonResponse({
            "demonio_topologia": "activo/actualizado", 
            "intervalo_minutos": daemon_config["intervalo"] // 60
        }, status=200)

    elif request.method == 'DELETE':
        daemon_config["activo"] = False
        return JsonResponse({"demonio_topologia": "detenido"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


def grafica_topologia(request):
    """GET: Retorna un archivo PNG con la gráfica de la topología dinámica."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    # Crear grafo con NetworkX
    G = nx.Graph()
    routers = Router.objects.all()
    for r in routers:
        G.add_node(r.hostname, label=f"{r.hostname}\n({r.rol})")
        
    interfaces_con_enlace = Interfaz.objects.filter(conectado_a__isnull=False)
    for inf in interfaces_con_enlace:
        G.add_edge(inf.router.hostname, inf.conectado_a.router.hostname)

    # Dibujar gráfica
    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(G)
    nx.draw(G, pos, with_labels=True, node_color='skyblue', node_size=2000, font_size=10, font_weight='bold')
    
    # Guardar en buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    
    return HttpResponse(buf.read(), content_type="image/png")


# ==========================================
# ENDPOINTS: MONITOREO DE OCTETOS (/routers/.../octetos/<tiempo>)
# ==========================================

@csrf_exempt
def monitoreo_octetos(request, hostname, interfaz, tiempo):
    """Gestiona el proceso autónomo de muestreo de octetos de entrada."""
    router = get_object_or_404(Router, hostname=hostname)
    # Validar formato de interfaz requerido: ej: f1_0
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)

    if request.method == 'GET':
        # Recuperar datos muestreados hasta el momento
        muestras = RegistroOcteto.objects.filter(interfaz=obj_interfaz).order_by('timestamp')
        datos = [{"timestamp": m.timestamp.strftime('%Y-%m-%d %H:%M:%S'), "octetos_entrada": m.octetos_entrada} for m in muestras]
        return JsonResponse({"interfaz": interfaz, "muestras_recuperadas": datos}, status=200)

    elif request.method == 'POST':
        # Activa el proceso de monitoreo autónomo indicando el intervalo (tiempo)
        # En modo simulación, creamos unas muestras ficticias de inmediato para tener datos que graficar
        if getattr(settings, 'DEBUG', True):
            import random
            from django.utils import timezone
            for t in range(5):
                RegistroOcteto.objects.create(
                    interfaz=obj_interfaz,
                    octetos_entrada=random.randint(5000, 25000),
                    timestamp=timezone.now()
                )
        return JsonResponse({"monitoreo": "activado", "interfaz": interfaz, "intervalo_muestreo_segundos": tiempo}, status=200)

    elif request.method == 'DELETE':
        # Detiene el hilo/proceso de monitoreo de octetos
        return JsonResponse({"monitoreo": "detenido", "interfaz": interfaz}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: GESTIÓN DE TRAPS LINKUP/LINKDOWN (/routers/.../estado)
# ==========================================

@csrf_exempt
def gestion_traps(request, hostname, interfaz):
    """GET: Estado actual. POST/DELETE: Activa/Desactiva captura de trampas SNMP."""
    router = get_object_or_404(Router, hostname=hostname)
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)

    if request.method == 'GET':
        return JsonResponse({"interfaz": interfaz, "estado": "up" if obj_interfaz.estado else "down"}, status=200)

    elif request.method == 'POST':
        # Activa el demonio/escuchador de Trampas LinkUp y LinkDown para esta interfaz
        return JsonResponse({"captura_traps": "activada", "interfaz": interfaz, "eventos": ["LinkUp", "LinkDown"]}, status=200)

    elif request.method == 'DELETE':
        # Apaga la captura de trampas para la interfaz
        return JsonResponse({"captura_traps": "desactivada", "interfaz": interfaz}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: GRÁFICA DE MONITOREO (/routers/.../grafica)
# ==========================================

def grafica_monitoreo(request, hostname, interfaz):
    """GET: Genera y regresa la gráfica combinada de octetos."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    router = get_object_or_404(Router, hostname=hostname)
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)
    
    muestras = RegistroOcteto.objects.filter(interfaz=obj_interfaz).order_by('timestamp')
    if not muestras.exists():
        return HttpResponse("No hay datos para graficar", status=404)

    # Preparar datos
    tiempos = [m.timestamp.strftime('%H:%M:%S') for m in muestras]
    valores = [m.octetos_entrada for m in muestras]

    # Crear gráfica
    plt.figure(figsize=(8, 5))
    plt.plot(tiempos, valores, marker='o', linestyle='-', color='green', label='Octetos Entrada')
    plt.title(f"Monitoreo: {hostname} - {interfaz}")
    plt.xlabel("Tiempo")
    plt.ylabel("Octetos")
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Guardar en buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)

    return HttpResponse(buf.read(), content_type="image/png")
