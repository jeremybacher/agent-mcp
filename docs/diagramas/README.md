# Diagramas

| Diagrama | HTML interactivo | Imágenes | Fuente |
|---|---|---|---|
| Arquitectura | [arquitectura.html](arquitectura.html) | [claro](img/arquitectura-claro.png) · [oscuro](img/arquitectura-oscuro.png) | [arquitectura.json](fuente/arquitectura.json) |
| Una pregunta en el chat | [secuencia-chat.html](secuencia-chat.html) | [claro](img/secuencia-chat-claro.png) · [oscuro](img/secuencia-chat-oscuro.png) | [secuencia-chat.json](fuente/secuencia-chat.json) |
| Verificación de CUITs | [flujo-verificacion.html](flujo-verificacion.html) | [claro](img/flujo-verificacion-claro.png) · [oscuro](img/flujo-verificacion-oscuro.png) | [flujo-verificacion.json](fuente/flujo-verificacion.json) |
| Fronteras de confianza | [seguridad.html](seguridad.html) | [claro](img/seguridad-claro.png) · [oscuro](img/seguridad-oscuro.png) | [seguridad.json](fuente/seguridad.json) |

Los HTML son autocontenidos: descargalos y abrilos en el navegador (GitHub muestra su código fuente, no la
página). Tienen zoom, tema claro y oscuro, y exportación.

## De dónde sale cada afirmación

Cada nodo cita los archivos y las líneas del código que lo respaldan (`sources` en los JSON). Las citas y los
enlaces del HTML apuntan al commit `a681debcb2aa463538d5f782fbbd84d0193dceca`, así que siguen siendo válidos
aunque el código cambie después: si el código evoluciona, conviene regenerar el diagrama contra el nuevo commit.

## Regenerar

Los diagramas se generan con la skill [Archify](https://github.com/tt-a1i/archify). Desde la raíz del repositorio:

```bash
node <ruta-de-archify>/bin/archify.mjs finalize architecture \
  docs/diagramas/fuente/arquitectura.json docs/diagramas/arquitectura.html \
  --repo-root . --quality showcase
```

Los tipos son `architecture` (arquitectura y seguridad), `sequence` (secuencia-chat) y `workflow`
(flujo-verificacion). Al terminar se genera, junto a cada HTML, un conjunto de recibos de verificación
(`*.finalize*.json`, `*.browser-check.json`, `*.delivery.json`); no se versionan.

Las imágenes salen de `archify visual-check <html> --summary --require-provenance --out-dir <carpeta>`
(capturas de 2048×1320 en claro y oscuro).
