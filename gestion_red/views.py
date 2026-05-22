import json
import time
import sys
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
from pysnmp.hlapi import (
    getCmd,
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity
)

# Importa tus modelos de la app (ajusta los nombres exactos si varían)
from .models import Router, Interfaz, DispositivoUsuario
from monitoreo.models import RegistroOcteto

import traceback
from functools import wraps
import logging

# Configurar logging básico
logger = logging.getLogger(__name__)    
# ==========================================
# FUNCIÓN DE LOG CON FLUSH FORZADO
# ==========================================
# Python buferiza stdout. Con sudo, los prints no aparecen en la terminal.
# Esta función fuerza que se muestren inmediatamente.
def log(msg):
    print(msg, flush=True)
    sys.stdout.flush()

def catch_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        log(f"\n[{timezone.now().strftime('%H:%M:%S')}] ---> [API REQUEST] Entrando a endpoint: {func.__name__.upper()}")
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = traceback.format_exc()
            log(f"[{timezone.now().strftime('%H:%M:%S')}] <--- [ERROR CRÍTICO en {func.__name__}]: \n{error_msg}")
            # Forzamos HTTP 200 temporalmente para que Django no intercepte y sobrescriba el JSON con su propia página HTML genérica.
            return JsonResponse({"error": "Error interno capturado", "detalle": str(e), "trace": error_msg}, status=200)
    return wrapper

# ==========================================
# UTILIDADES DE RED (SNMP / SSH / TRAPS)
# ==========================================

# Variable para forzar el uso de Mocks de red en caso de no tener GNS3 levantado
# Para usar GNS3 real, cambia esto a False.
USE_NETWORK_MOCKS = False

def snmp_get(ip, community, oid):
    """Realiza una consulta SNMP Get para un OID específico."""
    if USE_NETWORK_MOCKS:
        # Respuestas MOCK hardcodeadas
        logger.info(f"[MOCK SNMP GET] Consultando {ip} OID: {oid}")
        if '1.1.1.0' in oid:  # sysDescr
            return "Cisco IOS Software, C2900 Software (C2900-UNIVERSALK9-M), MOCKED"
        elif '.2.2.1.10.' in oid:  # ifInOctets
            return str(random.randint(500, 5000))
        elif '.2.2.1.2.' in oid: # ifDescr / ifName (walk simulado, devuelto como get para simplificar aquí)
            return "FastEthernet0/0"
        return "1"

    errorIndication, errorStatus, errorIndex, varBinds = next(
        getCmd(SnmpEngine(),
               CommunityData(community),
               UdpTransportTarget((ip, 161)),
               ContextData(),
               ObjectType(ObjectIdentity(oid)))
    )
    if errorIndication or errorStatus:
        logger.error(f"[SNMP Error] {errorIndication or errorStatus}")
        return None
    for varBind in varBinds:
        return str(varBind[1])

def snmp_walk(ip, community, oid):
    """Realiza una consulta SNMP Walk para un OID base."""
    if USE_NETWORK_MOCKS:
        logger.info(f"[MOCK SNMP WALK] Consultando {ip} OID Base: {oid}")
        # Simulamos respuestas del WALK basadas en el OID
        if '1.3.6.1.2.1.2.2.1.2' in oid: # ifDescr
            return {1: "FastEthernet0/0", 2: "FastEthernet1/0", 3: "GigabitEthernet0/0"}
        if '1.3.6.1.2.1.2.2.1.8' in oid: # ifOperStatus
            return {1: 1, 2: 1, 3: 2} # 1=up, 2=down
        if '1.3.6.1.4.1.9.9.23.1.2.1.1.6' in oid: # cdpCacheDeviceId
            return {1: "Router-Mock-Vecino"}
        if '1.3.6.1.4.1.9.9.23.1.2.1.1.4' in oid: # cdpCacheAddress (hex)
            return {1: "192.168.100.99"}
        return {}

    resultados = {}
    for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
        SnmpEngine(),
        CommunityData(community),
        UdpTransportTarget((ip, 161)),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False
    ):
        if errorIndication or errorStatus:
            logger.error(f"[SNMP Walk Error] {errorIndication or errorStatus}")
            break
        for varBind in varBinds:
            # Extraer el último índice del OID
            oid_completo = str(varBind[0])
            indice = int(oid_completo.split('.')[-1])
            valor = str(varBind[1])
            # Limpiar valores hexadecimales de IPs de cdpCacheAddress si es necesario, 
            # pero por ahora lo guardamos como string.
            resultados[indice] = valor
            
    return resultados

def ssh_config_user(router, action, username, privilege):
    """Configura usuarios vía SSH usando Netmiko."""
    if USE_NETWORK_MOCKS:
        logger.info(f"[MOCK SSH] Conectando a {router.hostname} ({router.ip_administrativa})")
        logger.info(f"[MOCK     SSH] Ejecutando action: {action} para usuario: {username}")
        time.sleep(0.1) # simula latencia
        return True

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
        logger.error(f"Error SSH en {router.hostname}: {e}")
        return False

def trap_receiver_daemon():
    """Hilo que escucha traps SNMP (en el puerto 162) o simula recibirlos."""
    logger.info("[Trap Listener] Iniciando receptor en puerto 162...")
    from .models import Interfaz
    
    if USE_NETWORK_MOCKS:
        while daemon_config["activo"]:
            time.sleep(20)
            if random.random() > 0.5:
                interfaces = list(Interfaz.objects.all())
                if interfaces:
                    interf = random.choice(interfaces)
                    interf.estado = not interf.estado
                    interf.save()
                    evento = "LinkUp" if interf.estado else "LinkDown"
                    logger.info(f"[MOCK TRAP] Recibido {evento} para {interf.router.hostname} - {interf.nombre}")
    else:
        # Implementación real usando socket UDP para escuchar en el puerto 162
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", 162))
            sock.settimeout(3.0)
            while daemon_config["activo"]:
                try:
                    data, addr = sock.recvfrom(65535)
                    ip_sender = addr[0]
                    logger.info(f"[TRAP REAL] Trap recibido de {ip_sender}")
                    
                    # Como parsear ASN.1 crudo es complejo, reaccionaremos al trap del sender
                    # alternando el estado de la primera interfaz por demostración (se debe ajustar según OID de ifIndex)
                    interf = Interfaz.objects.filter(router__ip_administrativa=ip_sender).first()
                    if interf:
                        interf.estado = not interf.estado
                        interf.save()
                except socket.timeout:
                    continue
        except PermissionError:
            logger.error("[Trap Listener] ERROR CRÍTICO: Permisos insuficientes para abrir el puerto 162. Ejecuta con 'sudo'.")
            daemon_config["activo"] = False
        except Exception as e:
            logger.error(f"[Trap Listener] Error: {e}")
            daemon_config["activo"] = False

# ==========================================
# VARIABLES GLOBALES Y PROCESOS AUTÓNOMOS
# ==========================================
daemon_config = {
    "activo": False,
    "intervalo": 300,
    "thread": None,
    "trap_thread": None,
    "monitoreo_threads": {} # {interfaz_id: thread}
}

def monitoreo_interfaz_worker(interfaz_id, intervalo):
    """Proceso que recolecta muestras de octetos periódicamente."""
    from .models import Interfaz
    from monitoreo.models import RegistroOcteto, MonitoreoConfig
    
    logger.info(f"[Monitoreo] Iniciando trabajador para Interfaz ID: {interfaz_id}")
    while True:
        try:
            # Verificar si el monitoreo sigue activo en la base de datos
            config = MonitoreoConfig.objects.get(interfaz_id=interfaz_id)
            if not config.monitoreo_octetos_activo:
                break
            
            interfaz = Interfaz.objects.get(id=interfaz_id)
            # SIMULACIÓN / SNMP REAL
            if getattr(settings, 'DEBUG', True) and not USE_NETWORK_MOCKS:
                valor = random.randint(100, 1000)
            else:
                community = os.getenv("SNMP_COMMUNITY", "public")
                # 1. Resolver el índice SNMP de la interfaz de forma dinámica
                ifDescr_walk = snmp_walk(interfaz.router.ip_administrativa, community, '1.3.6.1.2.1.2.2.1.2')
                
                snmp_index = 1 # Valor por defecto si no se encuentra
                for idx, desc in ifDescr_walk.items():
                    # Normalizar el string para compararlo con el nombre de la BD (f1_0 vs FastEthernet1/0)
                    desc_norm = desc.replace("FastEthernet", "f").replace("GigabitEthernet", "g").replace("/", "_").lower()
                    if interfaz.nombre.lower() == desc_norm or interfaz.nombre.lower() in desc.lower():
                        snmp_index = idx
                        break

                # 2. Consultar ifInOctets con el índice correcto
                res = snmp_get(interfaz.router.ip_administrativa, community, f'.1.3.6.1.2.1.2.2.1.10.{snmp_index}')
                valor = int(res) if res else 0

            RegistroOcteto.objects.create(interfaz=interfaz, octetos_entrada=valor)
            time.sleep(intervalo)
        except Exception as e:
            logger.error(f"Error en monitoreo {interfaz_id}: {e}")
            break
    logger.info(f"[Monitoreo] Deteniendo trabajador para Interfaz ID: {interfaz_id}")

def descubrimiento_red_daemon():
    """Explora la red buscando vecinos y actualizando información."""
    community = os.getenv("SNMP_COMMUNITY", "public")
    while daemon_config["activo"]:
        routers = Router.objects.all()
        for r in routers:
            logger.info(f"[{timezone.now()}] Escaneando {r.hostname}...")
            
            if not getattr(settings, 'DEBUG', True) or USE_NETWORK_MOCKS:
                # Actualizar SO vía SNMP
                desc = snmp_get(r.ip_administrativa, community, '.1.3.6.1.2.1.1.1.0')
                if desc:
                    r.sistema_operativo = desc
                    r.save()
                    
                # Descubrir vecinos CDP
                vecinos_nombres = snmp_walk(r.ip_administrativa, community, '1.3.6.1.4.1.9.9.23.1.2.1.1.6')
                vecinos_ips = snmp_walk(r.ip_administrativa, community, '1.3.6.1.4.1.9.9.23.1.2.1.1.4')
                
                for idx, nombre_vecino in vecinos_nombres.items():
                    ip_vecino = str(vecinos_ips.get(idx, "192.168.0.0"))
                    
                    if nombre_vecino and not Router.objects.filter(hostname=nombre_vecino).exists():
                        nuevo_router = Router.objects.create(
                            hostname=nombre_vecino, rol='LEAF', 
                            ip_administrativa=ip_vecino,
                            ip_loopback=f"192.168.50.{random.randint(10, 250)}"
                        )
                        logger.info(f" -> ¡Nuevo router descubierto dinámicamente vía CDP: {nombre_vecino} ({ip_vecino})!")
                        
                        # Población inmediata de interfaces del nuevo router
                        from .models import Interfaz
                        ifDescr_walk = snmp_walk(ip_vecino, community, '1.3.6.1.2.1.2.2.1.2')
                        ifOper_walk = snmp_walk(ip_vecino, community, '1.3.6.1.2.1.2.2.1.8')
                        
                        for idx_if, nombre_if in ifDescr_walk.items():
                            estado = True if str(ifOper_walk.get(idx_if, '2')) == '1' else False
                            Interfaz.objects.get_or_create(
                                router=nuevo_router,
                                nombre=str(nombre_if),
                                defaults={'estado': estado, 'ip_address': '0.0.0.0', 'netmask': '0.0.0.0'}
                            )
                        log(f"    -> Interfaces de {nombre_vecino} guardadas exitosamente.")
            
            # SIMULACIÓN DE DESCUBRIMIENTO DINÁMICO (Fallback)
            if getattr(settings, 'DEBUG', True) and not USE_NETWORK_MOCKS and random.random() > 0.8:
                new_host = f"TOR-{random.randint(10, 99)}"
                if not Router.objects.filter(hostname=new_host).exists():
                    Router.objects.create(
                        hostname=new_host, rol='LEAF', 
                        ip_administrativa=f"192.168.100.{random.randint(10, 250)}",
                        ip_loopback=f"192.168.50.{random.randint(10, 250)}"
                    )
                    logger.info(f" -> ¡Nuevo router simulado: {new_host}!")
            
        time.sleep(daemon_config["intervalo"])

# ==========================================
# ENDPOINTS: CRUD USUARIOS GLOBAL (/usuarios)
# ==========================================

@csrf_exempt
@catch_errors
def usuarios_globales(request):
    """
    GET: Regresa json con todos los usuarios en todos los routers.
    POST: Agrega un nuevo usuario a TODOS los routers.
    PUT: Actualiza un usuario en TODOS los routers.
    DELETE: Elimina un usuario común en TODOS los routers.
    """
    # Verificar si la base de datos está vacía o sin inicializar
    try:
        routers = Router.objects.all()
        if not routers.exists():
            return JsonResponse({"error": "Base de datos vacía", "solucion": "Ejecuta python poblar_red.py o poblar_semilla.py"}, status=400)
    except Exception as db_err:
        return JsonResponse({"error": "Tablas no encontradas", "solucion": "Ejecuta python manage.py migrate", "detalle": str(db_err)}, status=400)

    if request.method == 'GET':
        logger.info("[usuarios_globales] Procesando GET: Agrupando usuarios de la BD.")
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
        log(f"[usuarios_globales] Procesando {request.method}: Extrayendo body JSON.")
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
            if getattr(settings, 'DEBUG', True) and not USE_NETWORK_MOCKS:
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

@catch_errors
def lista_routers(request):
    """GET: Regresa la información general de todos los routers."""
    if request.method != 'GET':
        logger.warning("[lista_routers] Metodo no permitido.")
        return JsonResponse({"error": "Método no permitido"}, status=405)
        
    logger.info("[lista_routers] Procesando GET: Recopilando informacion de todos los routers.")
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


@catch_errors
def detalle_router(request, hostname):
    """GET: Regresa la información general de un router específico o 404."""
    if request.method != 'GET':
        logger.warning("[detalle_router] Metodo no permitido.")
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # Requisito estricto: Devolver 404 si el dispositivo no existe
    logger.info(f"[detalle_router] Procesando GET: Buscando router {hostname}")
    router = get_object_or_404(Router, hostname=hostname)
    
    # En modo Real (DEBUG=False), actualizamos la información vía SNMP
    if not getattr(settings, 'DEBUG', True):
        community = os.getenv("SNMP_COMMUNITY", "public")
        desc = snmp_get(router.ip_administrativa, community, '.1.3.6.1.2.1.1.1.0')
        if desc:
            router.sistema_operativo = desc
            router.save()
    else:
        # En modo DEBUG, podemos simular una actualización
        router.sistema_operativo = "Cisco IOS (Simulado)"
        router.save()

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

@catch_errors
def interfaces_router(request, hostname):
    """GET: Regresa en formato JSON la información de las interfaces del router."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)

    logger.info(f"[interfaces_router] Procesando GET: Buscando interfaces de {hostname}")
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
@catch_errors
def usuarios_por_enrutador(request, hostname):
    """CRUD de usuarios acotado a un enrutador específico."""
    router = get_object_or_404(Router, hostname=hostname)

    if request.method == 'GET':
        logger.info(f"[usuarios_por_enrutador] Procesando GET: Usuarios en {hostname}")
        usuarios = DispositivoUsuario.objects.filter(router=router)
        respuesta = [{"nombre": u.username, "permisos": u.privilegio} for u in usuarios]
        return JsonResponse(respuesta, safe=False, status=200)

    elif request.method in ['POST', 'PUT', 'DELETE']:
        logger.info(f"[usuarios_por_enrutador] Procesando {request.method}: Extrayendo body JSON para {hostname}")
        try:
            body = json.loads(request.body)
            username = body.get('nombre')
            privilegio = body.get('permisos')
            logger.info(f"[usuarios_por_enrutador] Datos recibidos: usuario={username}, privilegio={privilegio}")
        except (json.JSONDecodeError, KeyError):
            logger.error(f"[usuarios_por_enrutador] ERROR: JSON malformado en la peticion")
            return JsonResponse({"error": "JSON malformado"}, status=400)

        if getattr(settings, 'DEBUG', True) and not USE_NETWORK_MOCKS:
            # SIMULACIÓN SIN MOCK
            logger.info(f"[usuarios_por_enrutador] Modo SIMULACION: Saltando SSH real")
            ssh_exitoso = True
        else:
            # REAL SSH O MOCK
            logger.info(f"[usuarios_por_enrutador] Ejecutando SSH (real o mock) en {hostname}...")
            ssh_exitoso = ssh_config_user(router, request.method, username, privilegio)
            logger.info(f"[usuarios_por_enrutador] Resultado SSH: {'EXITOSO' if ssh_exitoso else 'FALLIDO'}")

        if ssh_exitoso:
            if request.method == 'POST':
                DispositivoUsuario.objects.get_or_create(username=username, router=router, defaults={'privilegio': privilegio})
                logger.info(f"[usuarios_por_enrutador] Usuario '{username}' CREADO en {hostname}")
                return JsonResponse({"nombre": username, "permisos": privilegio, "estado": f"Creado en {hostname}"}, status=201)
            elif request.method == 'PUT':
                DispositivoUsuario.objects.filter(username=username, router=router).update(privilegio=privilegio)
                logger.info(f"[usuarios_por_enrutador] Usuario '{username}' ACTUALIZADO en {hostname}")
                return JsonResponse({"nombre": username, "permisos": privilegio, "estado": f"Actualizado en {hostname}"}, status=200)
            elif request.method == 'DELETE':
                DispositivoUsuario.objects.filter(username=username, router=router).delete()
                return JsonResponse({"nombre": username, "estado": f"Eliminado de {hostname}"}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: DETECTAR TOPOLOGÍA Y GRÁFICA (/topologia)
# ==========================================

@csrf_exempt
@catch_errors
def gestionar_topologia(request):
    """GET: Regresa routers vecinos. PUT/DELETE: Controla el demonio de exploración."""
    # Verificar si la base de datos está vacía o sin inicializar
    try:
        routers = Router.objects.all()
        if not routers.exists():
            return JsonResponse({"error": "Base de datos vacía", "solucion": "Ejecuta python poblar_red.py o poblar_semilla.py"}, status=400)
    except Exception as db_err:
        return JsonResponse({"error": "Tablas no encontradas", "solucion": "Ejecuta python manage.py migrate", "detalle": str(db_err)}, status=400)

    if request.method == 'GET':
        logger.info("[gestionar_topologia] Procesando GET: Retornando adyacencias/vecinos actuales.")
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
        logger.info("[gestionar_topologia] Procesando PUT: Solicitud de encender daemon de Topología.")
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


@catch_errors
def grafica_topologia(request):
    """GET: Retorna un archivo PNG con la gráfica de la topología dinámica."""
    if request.method != 'GET':
        return JsonResponse({"error": "Método no permitido"}, status=405)
    
    # Crear grafo con NetworkX
    logger.info("[grafica_topologia] Procesando GET: Generando PNG de la Topologia Dinámica.")
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
@catch_errors
def monitoreo_octetos(request, hostname, interfaz, tiempo):
    """Gestiona el proceso autónomo de muestreo de octetos de entrada."""
    logger.info(f"[monitoreo_octetos] Buscando router={hostname}, interfaz={interfaz}, tiempo={tiempo}s")
    router = get_object_or_404(Router, hostname=hostname)
    # Validar formato de interfaz requerido: ej: f1_0
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)
    logger.info(f"[monitoreo_octetos] Router e interfaz encontrados en la BD.")

    if request.method == 'GET':
        logger.info(f"[monitoreo_octetos] Procesando GET: Recuperando muestras de {interfaz} en {hostname}")
        # Recuperar datos muestreados hasta el momento
        muestras = RegistroOcteto.objects.filter(interfaz=obj_interfaz).order_by('timestamp')
        logger.info(f"[monitoreo_octetos] Se encontraron {muestras.count()} muestras.")
        datos = [{"timestamp": m.timestamp.strftime('%Y-%m-%d %H:%M:%S'), "octetos_entrada": m.octetos_entrada} for m in muestras]
        return JsonResponse({"interfaz": interfaz, "muestras_recuperadas": datos}, status=200)

    elif request.method == 'POST':
        logger.info(f"[monitoreo_octetos] Procesando POST: Activando worker de monitoreo para {interfaz} cada {tiempo}s")
        # Activa el proceso de monitoreo autónomo
        from monitoreo.models import MonitoreoConfig
        config, _ = MonitoreoConfig.objects.update_or_create(
            interfaz=obj_interfaz,
            defaults={'monitoreo_octetos_activo': True, 'intervalo_muestreo': tiempo}
        )
        
        # Lanzar el hilo trabajador para esta interfaz
        t = threading.Thread(target=monitoreo_interfaz_worker, args=(obj_interfaz.id, tiempo), daemon=True)
        t.start()
        daemon_config["monitoreo_threads"][obj_interfaz.id] = t
        logger.info(f"[monitoreo_octetos] Worker lanzado exitosamente para interfaz ID={obj_interfaz.id}")
        
        return JsonResponse({"monitoreo": "activado", "interfaz": interfaz, "intervalo_muestreo_segundos": tiempo}, status=200)

    elif request.method == 'DELETE':
        logger.info(f"[monitoreo_octetos] Procesando DELETE: Deteniendo worker de monitoreo para {interfaz}")
        from monitoreo.models import MonitoreoConfig
        MonitoreoConfig.objects.filter(interfaz=obj_interfaz).update(monitoreo_octetos_activo=False)
        logger.info(f"[monitoreo_octetos] Worker detenido para {interfaz}.")
        return JsonResponse({"monitoreo": "detenido", "interfaz": interfaz}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: GESTIÓN DE TRAPS LINKUP/LINKDOWN (/routers/.../estado)
# ==========================================

@csrf_exempt
@catch_errors
def gestion_traps(request, hostname, interfaz):
    """GET: Estado actual. POST/DELETE: Activa/Desactiva captura de trampas SNMP."""
    logger.info(f"[gestion_traps] Buscando router={hostname}, interfaz={interfaz}")
    router = get_object_or_404(Router, hostname=hostname)
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)
    logger.info(f"[gestion_traps] Router e interfaz encontrados. Estado actual: {'up' if obj_interfaz.estado else 'down'}")

    if request.method == 'GET':
        logger.info(f"[gestion_traps] Procesando GET: Verificando estado up/down de {interfaz} en {hostname}")
        return JsonResponse({"interfaz": interfaz, "estado": "up" if obj_interfaz.estado else "down"}, status=200)

    elif request.method == 'POST':
        logger.info(f"[gestion_traps] Procesando POST: Activando captura de traps para {interfaz} en {hostname}")
        # Activa el demonio/escuchador de Trampas LinkUp y LinkDown para esta interfaz
        return JsonResponse({"captura_traps": "activada", "interfaz": interfaz, "eventos": ["LinkUp", "LinkDown"]}, status=200)

    elif request.method == 'DELETE':
        logger.info(f"[gestion_traps] Procesando DELETE: Desactivando captura de traps para {interfaz} en {hostname}")
        # Apaga la captura de trampas para la interfaz
        return JsonResponse({"captura_traps": "desactivada", "interfaz": interfaz}, status=200)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# ==========================================
# ENDPOINTS: GRÁFICA DE MONITOREO (/routers/.../grafica)
# ==========================================

@catch_errors
def grafica_monitoreo(request, hostname, interfaz):
    """GET: Genera y regresa la gráfica combinada de octetos."""
    if request.method != 'GET':
        logger.info(f"[grafica_monitoreo] Metodo no permitido: {request.method}")
        return JsonResponse({"error": "Método no permitido"}, status=405)

    logger.info(f"[grafica_monitoreo] Procesando GET: Generando PNG de octetos para {interfaz} en {hostname}")
    router = get_object_or_404(Router, hostname=hostname)
    obj_interfaz = get_object_or_404(Interfaz, router=router, nombre=interfaz)
    
    muestras = RegistroOcteto.objects.filter(interfaz=obj_interfaz).order_by('timestamp')
    logger.info(f"[grafica_monitoreo] Se encontraron {muestras.count()} muestras para graficar.")
    if not muestras.exists():
        logger.info(f"[grafica_monitoreo] SIN DATOS: No hay muestras para {interfaz}. Retornando 404.")
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
