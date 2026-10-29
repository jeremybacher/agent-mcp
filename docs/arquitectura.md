# Arquitectura del agente de proveedores

## Problema

Un área de compras o contabilidad recibe CUITs de proveedores y tiene que
confirmar que existen, que están activos y qué actividad declaran antes de
contratar o pagar. Hacerlo a mano en el portal de ARCA es lento y propenso a
errores de tipeo. El agente lo automatiza y deja las excepciones señaladas para
que las revise una persona.

## Componentes

```
usuario ──► agent.py ──► agente.runner ──► Gemini (function calling)
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
| `agente/entradas.py` | CSV acotado y ruta de salida confinada |
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
| Fuga de la API key | Solo se lee de `GEMINI_API_KEY`; no se escribe en trazas ni en informes |
| Exposición de datos personales | El servidor descarta DNI, fecha de nacimiento y domicilio |

## Límites conocidos

- El modelo puede equivocarse al redactar el informe aunque los datos de las
  herramientas sean correctos. Las alertas orientan, no reemplazan una revisión.
- La lista blanca controla qué herramientas se ejecutan, no qué argumentos usa
  el modelo; por eso `consultar_cuit` valida el CUIT del lado del servidor.
- Las consultas se hacen contra producción de ARCA y son reales.
