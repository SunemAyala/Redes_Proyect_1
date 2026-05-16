from django.db import models

class Router(models.Model):
    # Definición de los roles fijos exigidos por la rúbrica
    ROLE_CHOICES = [
        ('EDGE', 'Edge (Frontera)'),
        ('CORE', 'Core (Núcleo)'),
        ('LEAF', 'Leaf (Hoja/TOR)'),
    ]

    # Usamos el hostname como llave primaria para limpiar las URLs tipo /routers/<hostname>/
    hostname = models.CharField(max_length=50, primary_key=True)
    ip_administrativa = models.GenericIPAddressField(protocol='IPv4', unique=True)
    ip_loopback = models.GenericIPAddressField(protocol='IPv4', unique=True)
    rol = models.CharField(max_length=10, choices=ROLE_CHOICES) # Tu propuesta de rol_router integrada
    empresa = models.CharField(max_length=100, default="Universidad")
    sistema_operativo = models.CharField(max_length=100, default="Cisco IOS")
    
    # Credenciales por defecto para que los demonios se conecten vía SSH
    ssh_usuario_admin = models.CharField(max_length=50, default="admin")
    ssh_password_admin = models.CharField(max_length=50, default="admin123")

    def __str__(self):
        return f"{self.hostname} ({self.rol})"


class Interfaz(models.Model):
    # Nomenclatura estricta exigida: f1_0, fastethernet1_0, etc.
    nombre = models.CharField(max_length=30)  
    ip_address = models.GenericIPAddressField(protocol='IPv4', blank=True, null=True)
    netmask = models.GenericIPAddressField(protocol='IPv4', blank=True, null=True)
    estado = models.BooleanField(default=True)  # True = Up, False = Down
    
    # Relación: Un router tiene muchas interfaces
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='interfaces')

    # ENLACE DINÁMICO (Autoreferencia / Self-referential relationship):
    # Mapea qué interfaz se conecta con qué otra interfaz vecina en la topología.
    # Esto resuelve los enlaces sin necesidad de una tabla "Switch" intermedia.
    conectado_a = models.OneToOneField(
        'self', 
        on_delete=models.SET_NULL, 
        blank=True, 
        null=True, 
        related_name='enlace_reciproco'
    )

    class Meta:
        unique_together = ('nombre', 'router') # Evita duplicados del mismo puerto en el mismo router

    def __str__(self):
        return f"{self.router.hostname} - {self.nombre}"


class DispositivoUsuario(models.Model):
    """
    Tu modelo 'usuarios'. Almacena las cuentas creadas mediante el CRUD
    y sabe en qué routers específicos existen.
    """
    username = models.CharField(max_length=50)
    privilegio = models.IntegerField(default=1) # Permisos SSH del 1 al 15
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='usuarios_red')

    class Meta:
        unique_together = ('username', 'router') # Un mismo usuario no se duplica en el mismo router

    def __str__(self):
        return f"User: {self.username} en {self.router.hostname}"# Create your models here.
