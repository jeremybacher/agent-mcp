# ARCA Agent

> Este es un proyecto personal e independiente, sin ninguna afiliación,
> respaldo ni vínculo oficial con ARCA, AFIP ni el Estado argentino.

Agente de debida diligencia de proveedores: recibe CUITs, los verifica contra
el Padrón de **ARCA** (la Agencia de Recaudación y Control Aduanero, antes
AFIP) y devuelve un informe en Markdown con alertas. El agente y sus skills se
definen de forma declarativa en archivos `.md` y usan Gemini como modelo. Ver
[Agente de proveedores](#agente-de-proveedores-gemini) y
[docs/arquitectura.md](docs/arquitectura.md).

El repo incluye el **servidor MCP** que le da acceso al Padrón: consulta datos
de un contribuyente (razón social, estado, actividad) a partir de su CUIT,
autenticando contra el Web Service de Autenticación y Autorización (WSAA) y
llamando al servicio de Consulta a Padrón (Alcance 13). Se puede usar solo,
desde cualquier cliente MCP, y trae un dashboard web que muestra la última
consulta en tiempo real.

> Nota: ARCA sigue usando la infraestructura técnica heredada de AFIP (los
> dominios de los web services y el portal de Clave Fiscal todavía son
> `afip.gob.ar`), así que las URLs de este proyecto apuntan ahí.

Corre contra el entorno de **producción** de ARCA: el certificado se gestiona
desde "Administración de Certificados Digitales" (no desde WSASS, que es
específico para el entorno de homologación/testing y quedó en desuso para
este flujo). Como `consultar_cuit` solo lee datos públicos del padrón, el
riesgo de usar producción es bajo, pero tené presente que las consultas son
reales.

## Requisitos previos

- Python 3.10 o superior
- OpenSSL (viene instalado en macOS/Linux)
- Un CUIT propio con Clave Fiscal nivel 3

## 1. Cómo iniciar sesión en ARCA (Clave Fiscal)

1. Entrá a **https://www.afip.gob.ar** (el organismo se renombró a ARCA, pero
   el dominio y el sistema de Clave Fiscal siguen siendo los mismos).
2. Click en **"Ingresar"**.
3. Ingresá tu **CUIT** y tu **Clave Fiscal** (la contraseña que gestionás en
   ese mismo portal). Para administrar certificados de webservices necesitás
   **nivel de seguridad 3** — si tenés un nivel menor, se sube desde el mismo
   sitio con un trámite adicional (token de seguridad / verificación).
4. Ya logueado, vas a ver el listado de "Servicios habilitados" asociados a
   tu Clave Fiscal.

## 2. Generar el certificado

Ningún web service de ARCA es público: hace falta un certificado digital
propio asociado a tu CUIT.

```bash
mkdir -p certs
openssl genrsa -out certs/clave_privada.key 2048
openssl req -new -key certs/clave_privada.key \
  -subj "/C=AR/O=TuNombre/CN=arca-agent-local/serialNumber=CUIT 20XXXXXXXXX" \
  -out certs/solicitud.csr
```

Reemplazá `TuNombre` y `20XXXXXXXXX` por tu nombre y tu CUIT sin guiones
(respetando el espacio entre `CUIT` y el número).

Con la sesión iniciada (paso 1):

1. En el buscador de servicios/trámites escribí **"webser"** y entrá a
   **"Administración de Certificados Digitales"**.
2. Click en **"Agregar alias"**. Completá un alias (ej. `arca-agent-local`) y
   subí `certs/solicitud.csr` con "Choose File".
3. Confirmá y descargá el `.crt` generado; guardalo como
   `certs/certificado.crt`.
4. Andá a **"Administrador de Relaciones de Clave Fiscal"** → **"Nueva
   Relación"**:
   - "Representado": tu propio CUIT (debería salir preseleccionado).
   - Primer botón "Buscar" → **ARCA → Web Services** → elegí
     **`ws_sr_padron_a13`**.
   - Segundo botón "Buscar" → seleccioná el certificado/alias que generaste.
   - Confirmá dos veces.

### Cómo revocar el acceso (por ejemplo, si dejás de usar el proyecto)

La forma más simple y acotada de cortar el acceso es revocar el
**certificado** en sí (no la relación): sin un certificado válido, WSAA
rechaza cualquier login sin importar qué relaciones existan, y la acción
queda limitada a ese certificado puntual sin tocar ningún otro servicio de tu
cuenta.

1. Entrá a **"Administración de Certificados Digitales"** (mismo lugar donde
   lo generaste).
2. Buscá el certificado con el alias que usaste (ej. `arca-agent-local`) en el
   listado de **"Certificados"**.
3. Usá la opción para revocarlo/darlo de baja.

(La otra vía —buscar y revocar la relación puntual en "Administrador de
Relaciones de Clave Fiscal" → "Consultar"— también funciona, pero ahí la
relación puede no figurar con un nombre reconocible: puede aparecer con el
nombre general del servicio, por ejemplo "Sistema registral", mezclada entre
decenas de otras relaciones que sí necesitás conservar. Preferí revocar el
certificado.)

Ni la clave privada ni el certificado se suben al repositorio (están en
`.gitignore`).

## 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Completá `.env` con tu CUIT y las rutas a los archivos generados en el paso 2.

## 4. Instalación

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Verificar la conexión

Antes de conectar el MCP, probá la autenticación y la consulta por separado:

```bash
python3 verificar_conexion.py
```

Si imprime un token y los datos de tu propio CUIT, la configuración es
correcta.

## 6. Ejecutar el servidor

```bash
python3 server.py
```

Levanta el servidor MCP (por stdio) y el dashboard en
`http://127.0.0.1:5050`.

## Configuración del MCP

El archivo `.mcp.json` en la raíz registra el servidor para que el editor lo
detecte automáticamente al abrir esta carpeta. No contiene credenciales: las
lee `server.py` desde `.env` en tiempo de ejecución.

## Cómo usarlo

Una vez conectado el servidor MCP (con cualquiera de los clientes de abajo) y
el dashboard abierto en `http://127.0.0.1:5050`, simplemente pedile en el
chat que use la herramienta, por ejemplo:

> "Consultá el CUIT 20XXXXXXXXX en el padrón de ARCA."

El asistente va a llamar a `consultar_cuit`, y en el dashboard vas a ver
reflejada la última consulta en tiempo real.

### Claude Code

Al abrir esta carpeta como proyecto, Claude Code detecta automáticamente el
`.mcp.json` de la raíz y te va a pedir confirmación para habilitar el
servidor `arca-agent`.

### Claude Desktop

Claude Desktop no lee `.mcp.json`: hay que registrar el servidor a mano en su
config global.

1. Abrí (o creá) el archivo de configuración:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
2. Agregá una entrada con **rutas absolutas** (Claude Desktop no corre desde
   la carpeta del proyecto, así que las rutas relativas no funcionan):

   ```json
   {
     "mcpServers": {
       "arca-agent": {
         "command": "/ruta/absoluta/a/arca-agent/venv/bin/python3",
         "args": ["/ruta/absoluta/a/arca-agent/server.py"]
       }
     }
   }
   ```

3. Reiniciá Claude Desktop. El servidor va a aparecer en el ícono de
   herramientas (🔨) del chat.

### Otros clientes MCP (Cursor, Windsurf, etc.)

Cualquier cliente que soporte el transporte estándar de MCP por stdio
funciona con el mismo patrón: apuntar `command` al Python del `venv` y
`args` a `server.py`, con rutas absolutas. Revisá la documentación propia de
cada cliente para saber dónde va ese JSON (suele ser un archivo de
configuración de MCP servers similar al de Claude Desktop).

## Herramientas expuestas por el MCP

| Herramienta | Descripción |
|---|---|
| `consultar_cuit(cuit)` | Autentica contra WSAA y consulta el CUIT en el Padrón de ARCA. Devuelve solo nombre, apellido, estado, actividad principal y tipo de persona — el resto (DNI, fecha de nacimiento, domicilio) se descarta a propósito antes de responder. Si el CUIT ya fue consultado antes, devuelve el resultado guardado en el historial local sin volver a llamar a ARCA. |
| `historial_consultas(limite=20)` | Lista las últimas consultas guardadas en el historial local (SQLite). |
| `buscar_en_historial(cuit)` | Busca si ya existe una consulta guardada para un CUIT, sin llamar a ARCA. |

## Historial de consultas

Cada consulta exitosa a `consultar_cuit` se guarda en `historial.db` (SQLite,
no se versiona). Las próximas consultas al mismo CUIT se responden desde ese
historial en vez de volver a autenticar y consultar el Padrón. El dashboard
web también expone este historial en `http://127.0.0.1:5050/historial`.

## Agente de proveedores (Gemini)

Sobre el MCP hay un agente de debida diligencia: recibe CUITs, consulta cada
uno a través de `consultar_cuit` y devuelve un informe en Markdown con una
tabla de proveedores y alertas (CUIT inválido, clave no activa, sin actividad
principal, persona física). Ver el diseño en [docs/arquitectura.md](docs/arquitectura.md).

El agente y sus skills se definen de forma declarativa, sin tocar código:

| Archivo | Qué define |
|---|---|
| `agents/analista-proveedores.agent.md` | Modelo, `temperature`, `max_output_tokens`, `max_tool_iterations`, skills habilitadas, servidor MCP y system prompt |
| `skills/verificar-proveedores/SKILL.md` | Herramientas permitidas (`consultar_cuit`), pasos, reglas de alerta y formato exacto del informe |
| `skills/resumen-historial/SKILL.md` | Consulta solo el historial local, nunca llama a ARCA |

### Configuración

1. Generá una API key en https://aistudio.google.com/apikey y ponela en `.env`
   como `GEMINI_API_KEY` (el archivo no se versiona).
2. `pip install -r requirements.txt`

Para cambiar el modelo o la temperatura se edita el frontmatter del
`.agent.md`; no hay valores fijos en el código.

### Uso

```bash
# Un pedido en lenguaje natural
python agent.py --skill verificar-proveedores "Verificá 30-00000006-6 y 20-00000002-8"

# Desde un CSV con columna `cuit`, guardando el informe en informes/
python agent.py --skill verificar-proveedores --csv ejemplos/proveedores.csv --salida hoy.md

# Qué ya se verificó (no consulta ARCA)
python agent.py --skill resumen-historial "¿Qué proveedores ya verifiqué?"
```

Con `--csv`, los CUITs con dígito verificador incorrecto se descartan antes de
llamar al modelo y se reportan como "CUIT inválido". Con un pedido en texto
libre los rechaza `consultar_cuit` en el servidor: igual no llegan a ARCA, pero
sí gastan tokens. La traza de cada herramienta que el agente invoca
sale por stderr.

### Seguridad

- **CUIT**: validación de prefijo y dígito verificador (módulo 11) en
  `validacion.py`, compartida por el servidor y el agente.
- **Skills acotadas**: el runner solo ejecuta las herramientas que declara la
  skill activa; cualquier otra se devuelve al modelo como error.
- **Frontmatter**: `yaml.safe_load` y nombres de skill restringidos a
  `[a-z0-9-]`, para que un `.agent.md` no pueda leer archivos fuera de `skills/`.
- **Salida**: `--salida` solo escribe archivos `.md` dentro de `informes/`
  (se resuelven symlinks y `..`).
- **CSV**: máximo 200 filas y 64 KB.
- **Datos del padrón como datos**: el system prompt indica ignorar texto con
  forma de instrucción en los campos devueltos y reportarlo como alerta.
- **Historial**: consultas SQL parametrizadas y `limite` acotado a 1-100.

## Tests

```bash
pytest
```

| Archivo | Tipo | Qué cubre |
|---|---|---|
| `test_validacion.py` | Unitario | CUIT (verificador, prefijos, unicode, inyección) y límites |
| `test_config_agente.py` | Unitario | Carga del `.agent.md`/skills, rangos, path traversal, YAML inseguro |
| `test_entradas.py` | Unitario | CSV acotado y confinamiento de la ruta de salida |
| `test_gemini.py` | Unitario | Configuración enviada a Gemini y traducción de respuestas (cliente falso) |
| `test_runner.py` | Integración | Bucle del agente con modelo y herramientas simulados |
| `test_mcp_integracion.py` | Integración | `ClienteMCP` contra `server.py` real por stdio (sin red) |
| `test_agente_integracion.py` | Integración | CLI completo: `.agent.md` y skill reales, servidor MCP real, runner y archivo de salida; solo el modelo es un doble |
| `test_server_consultar_cuit.py`, `test_historia.py` | Unitario | Servidor e historial, con ARCA mockeado |

Todos siguen el patrón Arrange-Act-Assert. Ningún test llama a ARCA ni a
Gemini. El repo incluye además un subagente de Claude Code,
`.claude/agents/generador-tests.agent.md`, para diseñar y refactorizar suites
con esas mismas reglas.

## Estructura del proyecto

```
arca-agent/
├── server.py             # MCP tools + servidor web embebido
├── agent.py               # CLI del agente de proveedores
├── agente/                  # config, runner, cliente MCP, adaptador Gemini, entradas
├── agents/                   # Definición declarativa del agente (.agent.md)
├── skills/                    # Skills del agente (SKILL.md)
├── validacion.py                # Validación de CUIT y límites
├── docs/arquitectura.md           # Diseño y modelo de amenazas
├── ejemplos/                       # CSV de ejemplo (datos ficticios)
├── informes/                        # Informes generados (no se versionan)
├── wsaa.py                # Login contra WSAA (firma CMS + token/sign, con cache)
├── padron.py               # Consulta al Padrón (Alcance 13)
├── historia.py              # Historial de consultas (SQLite)
├── verificar_conexion.py    # Script manual para probar la conexión
├── index.html                # Dashboard con actualización en tiempo real
├── tests/                      # Suite de tests (pytest)
├── certs/                     # Certificado y clave privada (no se versionan)
├── historial.db                # Historial de consultas (se genera solo, no se versiona)
├── token_cache.json            # Cache del token de WSAA (se genera solo, no se versiona)
├── requirements.txt
├── pytest.ini
├── .env.example
├── .mcp.json
└── README.md
```
