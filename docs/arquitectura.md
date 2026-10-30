# Arquitectura del agente de proveedores

## Problema

Un área de compras o contabilidad recibe CUITs de proveedores y tiene que
confirmar que existen, que están activos y qué actividad declaran antes de
contratar o pagar. Hacerlo a mano en el portal de ARCA es lento y propenso a
errores de tipeo. El agente lo automatiza y deja las excepciones señaladas para
que las revise una persona.

## Componentes

```
usuario ──► agent.py (CLI) ─┐
usuario ──► web.py (UI) ────┴► agente.runner ──► Gemini (function calling)
               │              │
               │              └─► agente.mcp_cliente ──stdio──► server.py
               │                                                  ├─ wsaa.py ──► WSAA
               │                                                  ├─ padron.py ─► Padrón A13
               │                                                  └─ historia.py ─► historial.db
               └─ lee agents/*.agent.md y skills/*/SKILL.md (agente.config)
```

| Módulo | Responsabilidad |
|---|---|
| `agente/config.py` | Parsea y valida el frontmatter del agente y las skills |
| `agente/runner.py` | Bucle modelo → herramienta → modelo, con tope de iteraciones |
| `agente/modelo.py` | Tipos neutrales (`Turno`, `LlamadaHerramienta`) y protocolo `Modelo` |
| `agente/gemini.py` | Único módulo que conoce `google-genai` |
| `agente/mcp_cliente.py` | Sesión MCP por stdio contra `server.py` |
| `agente/entradas.py` | CSV y texto pegado acotados, y ruta de salida confinada |
| `web.py` + `web/` | UI local de chat: lanza el agente en segundo plano (un trabajo a la vez), transmite sus eventos por Server-Sent Events, y lee y borra el historial directo de SQLite |
| `validacion.py` | CUIT con dígito verificador y límites numéricos |

## Decisiones

**Por qué MCP y no llamar a ARCA desde el agente.** El servidor ya existía y
ya filtra datos personales (DNI, fecha de nacimiento, domicilio) antes de
responder. El agente solo ve lo que el servidor decide exponer, y el mismo
servidor sigue sirviendo a Claude Code y a otros clientes.

**Por qué declarativo.** Cambiar de modelo, bajar la temperatura o agregar una
skill se hace editando Markdown. El código no tiene ningún valor de modelo
fijo.

**Por qué `temperature: 0`.** El informe tiene un formato exacto y se usa para
decidir pagos; se busca la salida más repetible posible. La repetibilidad
completa no está garantizada por el proveedor, pero la variación se reduce al
mínimo.

**Por qué function calling manual.** Con `automatic_function_calling`
desactivado, el runner ejecuta cada herramienta. Eso permite registrar cada
llamada, aplicar la lista blanca de la skill y cortar por iteraciones.

**Por qué una interfaz neutra de modelo.** `runner.py` no importa `google-genai`.
Los tests usan un modelo guionado y agregar otro proveedor (por ejemplo Ollama)
es implementar `Modelo.enviar` y sumarlo a `PROVIDERS_SOPORTADOS`.

**Por qué las preguntas sobre lo obtenido no guardan estado en el servidor.**
`consultar-datos` recibe como contexto los últimos turnos y el informe que la
página ya tiene. Así el servidor sigue sin sesiones ni memoria propia, y cada
ejecución abre y cierra su sesión MCP. Las respuestas a casos límite (dato que
no se guarda, CUIT no verificado, pregunta ajena) son frases fijas en la skill:
con un modelo económico, una instrucción general como "decí que no tiene
relación" se copiaba textualmente como respuesta.

**Por qué eventos y SSE.** El runner emite eventos (`texto`, `herramienta`,
`herramienta_fin`) en lugar de que la UI espere el resultado final. El adaptador
de Gemini usa `generate_content_stream` solo cuando alguien escucha, así que el
CLI y los tests siguen con la llamada simple. Cada trabajo guarda su registro de
eventos y el endpoint `/api/trabajos/<id>/eventos` los entrega en orden con un
`id` incremental: si la conexión se corta, el navegador retoma con `?desde=N`
sin perder ni repetir nada. Se eligió SSE sobre WebSocket porque el flujo es
unidireccional, funciona sobre HTTP común y no agrega dependencias. La
reconexión la controla la página (confirma que el servidor sigue ahí y se rinde
a los pocos segundos) en vez de la automática del navegador, que se espacia sin
límite y dejaba la UI colgada.

**Por qué una sola conversación y no un formulario por skill.** El usuario
piensa en "verificar" y "preguntar" como partes de un mismo diálogo (se verifica
un lote y enseguida se pregunta por él), así que ambas conviven en un hilo y las
preguntas ven el último informe como contexto. Aun así, qué skill corre lo elige
la persona con un selector visible y no el modelo: verificar consulta ARCA y
guarda datos, y eso no debe ocurrir porque una frase sonó a pedido. Como ayuda,
si lo pegado son solo CUITs el selector cambia solo a *Verificar* y avisa antes
de enviar, y al enviar vuelve a *Preguntar*.

**Por qué el borrado del historial es solo de la UI.** El servidor MCP expone
únicamente herramientas de lectura y de consulta a ARCA (hay un test que fija el
conjunto exacto), de modo que ni un error del modelo ni una inyección en un campo
del padrón puede borrar datos. La UI exige confirmación explícita, rechaza el
borrado si hay una ejecución en curso (que podría estar escribiendo en el mismo
momento) y borra con el candado de ejecución tomado, de modo que no pueda
empezar una consulta a mitad del borrado (revisar "no hay ejecución" y borrar
después dejaba ese hueco). Además, al vaciar todo, ejecuta `VACUUM`: sin él, SQLite deja el contenido
borrado en las páginas libres del archivo. Después de borrar, la conversación
registra un corte y el agente deja de ver lo anterior (turnos e informe), para
no responder con datos que ya no existen.

**Por qué la temperatura se cambia por ejecución y no en el archivo.** El
`.agent.md` sigue siendo la fuente de verdad. La UI y el CLI (`--temperature`)
solo envían un valor para esa ejecución, validado igual que el del archivo. Así
la UI no necesita permisos de escritura sobre la configuración del agente.

**Por qué las partes del modelo se guardan tal cual.** En el historial de
Gemini se conservan las partes como llegaron, incluidas las firmas de
razonamiento de las llamadas a herramientas: hay modelos que las exigen para
seguir una conversación con function calling.

**Por qué las herramientas devuelven `cuit_formateado`.** El modelo no armaba
de forma confiable `XX-XXXXXXXX-X`; formatear en el servidor es determinista.

**Por qué validar el CUIT antes.** Un CUIT con verificador incorrecto nunca
existe en el padrón. Descartarlo localmente evita una autenticación WSAA, una
consulta a ARCA y tokens del modelo.

## Modelo de amenazas

| Amenaza | Mitigación |
|---|---|
| Inyección de instrucciones vía campos del padrón (p. ej. razón social) | El system prompt trata la salida de herramientas como datos y exige reportarla como alerta; las herramientas están acotadas por skill |
| El modelo invoca una herramienta que la skill no declara | El runner la rechaza y devuelve un error al modelo |
| Bucle infinito de herramientas (costo, abuso de ARCA) | `max_tool_iterations` |
| Path traversal desde `--salida` o desde el nombre de una skill | Ruta resuelta con `realpath` dentro de `informes/`; nombres de skill con regex `[a-z0-9-]` |
| YAML malicioso en un `.agent.md` | `yaml.safe_load` |
| CSV enorme | Tope de 200 filas y 64 KB |
| Inyección SQL en el historial | Consultas parametrizadas; `limite` acotado |
| XSS: razón social u otro campo del padrón con HTML, o un informe del modelo con HTML | La UI inserta todo con `textContent` (renderizador de Markdown propio, sin HTML, imágenes ni enlaces) y la CSP prohíbe scripts y estilos inline |
| Otra página del navegador dispara consultas a la UI local (CSRF) o resuelve un dominio propio a 127.0.0.1 (DNS rebinding) | Se valida `Host` local, `Origin` del mismo sitio y `Content-Type: application/json`; el servidor escucha solo en 127.0.0.1 |
| Borrado accidental o forzado desde otra página (CSRF) o por el propio agente | El endpoint exige JSON, `Origin` propio y `{"confirmar": true}`; la UI pide confirmación; el agente no tiene ninguna herramienta de borrado |
| Datos que sobreviven al borrado en el archivo SQLite | `VACUUM` tras vaciar; un test comprueba que el texto borrado ya no está en el `.db` |
| Valor de `temperature` manipulado (NaN, infinito, texto, fuera de rango) | `validar_temperature` lo rechaza antes de llamar al modelo, en la UI y en el CLI |
| Pedido a Gemini colgado que deja tomado para siempre el cupo de la UI | Timeout de 60 s en el cliente: el trabajo termina con error y libera el cupo |
| Conexiones SSE colgadas que agotan hilos | Latido cada 15 s, el stream termina con el evento final y los eventos por trabajo están acotados |
| Uso abusivo de la UI (cuota de Gemini, llamadas a ARCA) | Una ejecución a la vez, cuerpos de hasta 128 KB, máximo 200 CUITs, 6 turnos de contexto y traza acotada |
| Instrucciones escondidas en el informe o la conversación que se reenvían como contexto en "Preguntar al agente" | Se delimitan como contexto de solo lectura y la skill solo dispone de herramientas de lectura del historial: en el peor caso, una respuesta equivocada; no se puede consultar ARCA ni escribir |
| Fuga de detalles internos al navegador | Los errores inesperados se registran en la terminal y la UI muestra un mensaje genérico |
| Fuga de la API key | Solo se lee de `GEMINI_API_KEY`; no se escribe en trazas ni en informes. El servidor MCP carga del `.env` únicamente las variables `ARCA_*` y el CLI solo le pasa `ARCA_HISTORIAL_DB`, así que la clave de Gemini no llega a ese subproceso |
| Exposición de datos personales | El servidor descarta DNI, fecha de nacimiento y domicilio |

## Límites conocidos

- El modelo puede equivocarse al redactar el informe aunque los datos de las
  herramientas sean correctos. Las alertas orientan, no reemplazan una revisión.
- La lista blanca controla qué herramientas se ejecutan, no qué argumentos usa
  el modelo; por eso `consultar_cuit` valida el CUIT del lado del servidor.
- Las consultas se hacen contra producción de ARCA y son reales.
