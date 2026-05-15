from django.db import models
from gestion_red.models import Interfaz # Importamos tu modelo de Interfaz para asociarle las métricas

class MonitoreoConfig(models.Model):
    """
    Control de estado para saber si el monitoreo o las trampas están activos 
    de forma independiente por interfaz, tal como lo pide la rúbrica.
    """
    interfaz = models.OneToOneField(Interfaz, on_delete=models.CASCADE, primary_key=True, related_name='config_monitoreo')
    monitoreo_octetos_activo = models.BooleanField(default=False) # POST/DELETE de octetos
    intervalo_muestreo = models.IntegerField(default=10) # En segundos, para el demonio
    captura_traps_activa = models.BooleanField(default=False) # POST/DELETE de estado (linkUp/Down)

    def __str__(self):
        return f"Config Monitoreo - {self.interfaz}"


class RegistroOcteto(models.Model):
    """
    Tu modelo 'octeto'. Guardará las muestras de octetos de entrada recolectadas 
    por SNMP para alimentar el generador de gráficas de Matplotlib.
    """
    interfaz = models.ForeignKey(Interfaz, on_delete=models.CASCADE, related_name='muestras_octetos')
    timestamp = models.DateTimeField(auto_now_add=True) # Fecha y hora exacta de la muestra
    octetos_entrada = models.BigIntegerField() # Contador de bytes/octetos

    class Meta:
        ordering = ['-timestamp'] # Organiza las muestras de la más reciente a la más antigua

    def __str__(self):
        return f"{self.interfaz.router.hostname} [{self.interfaz.nombre}] - {self.octetos_entrada} octetos"
# Create your models here.
