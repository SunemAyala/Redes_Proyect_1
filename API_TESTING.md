# Guía de Pruebas de la API REST (Comandos cURL)

Para probar la API de forma rápida sin depender de un Frontend, usa **cURL** desde la terminal o importa estas rutas en **Postman**. 

Asegúrate de que tu servidor Django esté corriendo (`sudo python manage.py runserver`).
*Nota: Reemplaza `Edge`, `f1_0` y `5` por valores reales si difieren.*

---

### 1. Usuarios Globales (`/usuarios/`)
* **GET** (Listar todos):
  `curl -X GET http://localhost:8000/usuarios/`
* **POST** (Crear usuario):
  `curl -X POST http://localhost:8000/usuarios/ -H "Content-Type: application/json" -d '{"nombre": "admin_red", "permisos": 15}'`
* **PUT** (Actualizar privilegios):
  `curl -X PUT http://localhost:8000/usuarios/ -H "Content-Type: application/json" -d '{"nombre": "admin_red", "permisos": 7}'`
* **DELETE** (Eliminar usuario global):
  `curl -X DELETE http://localhost:8000/usuarios/ -H "Content-Type: application/json" -d '{"nombre": "admin_red"}'`

---

### 2. Enrutadores (`/routers`)
* **GET** (Listar todos los routers generales):
  `curl -X GET http://localhost:8000/routers`
* **GET** (Detalle de un router específico):
  `curl -X GET http://localhost:8000/routers/Edge/`

---

### 3. Interfaces por Enrutador (`/routers/<hostname>/interfaces`)
* **GET** (Ver interfaces de `Edge`):
  `curl -X GET http://localhost:8000/routers/Edge/interfaces`

---

### 4. Usuarios por Enrutador (`/routers/<hostname>/usuarios/`)
* **GET** (Listar usuarios en `Edge`):
  `curl -X GET http://localhost:8000/routers/Edge/usuarios/`
* **POST** (Crear usuario solo en `Edge`):
  `curl -X POST http://localhost:8000/routers/Edge/usuarios/ -H "Content-Type: application/json" -d '{"nombre": "tecnico", "permisos": 5}'`
* **DELETE** (Borrar usuario de `Edge`):
  `curl -X DELETE http://localhost:8000/routers/Edge/usuarios/ -H "Content-Type: application/json" -d '{"nombre": "tecnico"}'`

---

### 5. Topología Dinámica (`/topologia`)
* **GET** (Ver JSON de vecinos conocidos):
  `curl -X GET http://localhost:8000/topologia`
* **PUT** (Encender Demonio CDP cada 1 minuto):
  `curl -X PUT http://localhost:8000/topologia -H "Content-Type: application/json" -d '{"intervalo": 1}'`
* **DELETE** (Apagar Demonio):
  `curl -X DELETE http://localhost:8000/topologia`
* **GET Gráfica PNG**: (Abre en tu navegador `http://localhost:8000/topologia/grafica`)

---

### 6. Monitoreo de Interfaz (Octetos)
* **POST** (Activar monitoreo cada `5` segundos):
  `curl -X POST http://localhost:8000/routers/Edge/interfaces/f1_0/octetos/5`
* **GET** (Ver el historial de muestras):
  `curl -X GET http://localhost:8000/routers/Edge/interfaces/f1_0/octetos/5`
* **DELETE** (Apagar el monitoreo):
  `curl -X DELETE http://localhost:8000/routers/Edge/interfaces/f1_0/octetos/5`
* **GET Gráfica PNG**: (Abre en tu navegador `http://localhost:8000/routers/Edge/interfaces/f1_0/grafica`)

---

### 7. Traps LinkUp / LinkDown
* **GET** (Ver el estado actual UP/DOWN):
  `curl -X GET http://localhost:8000/routers/Edge/interfaces/f1_0/estado`
* **POST** (Activar escucha de Traps):
  `curl -X POST http://localhost:8000/routers/Edge/interfaces/f1_0/estado`
* **DELETE** (Apagar escucha de Traps):
  `curl -X DELETE http://localhost:8000/routers/Edge/interfaces/f1_0/estado`
