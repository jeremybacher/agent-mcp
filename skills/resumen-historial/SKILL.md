---
name: resumen-historial
description: Responde qué proveedores ya fueron verificados consultando solo el historial local, sin llamar a ARCA.
tools:
  - historial_consultas
  - buscar_en_historial
inputs:
  - cuit: (opcional) un CUIT puntual a buscar
  - limite: (opcional) cantidad de consultas a listar, entre 1 y 100
outputs:
  - listado o respuesta puntual en Markdown, con fecha de cada consulta
---

# Skill: resumen-historial

## Cuándo usarla

Cuando el usuario pregunta qué proveedores ya se verificaron, si un CUIT ya
fue consultado, o pide un resumen de la actividad reciente. **Nunca** consulta
a ARCA: trabaja solo con el historial local.

## Pasos

1. Si el pedido menciona un CUIT puntual, llamá a `buscar_en_historial` con
   ese CUIT.
2. Si no, llamá a `historial_consultas` con el `limite` pedido (por defecto 20).
3. Si `buscar_en_historial` devuelve `encontrado: false`, decilo sin sugerir
   que el proveedor sea bueno o malo: solo que no fue verificado todavía.

## Formato de salida

```markdown
# Historial de verificaciones

| Fecha (UTC) | CUIT | Razón social | Estado |
|---|---|---|---|
| 2026-10-29 14:02 | 30-00000006-6 | ACME SA | ACTIVO |
```

Ordená de la más reciente a la más antigua. Si el historial está vacío,
respondé `Todavía no hay verificaciones guardadas.`

## Restricciones

- No inventes entradas ni completes campos faltantes.
- Si el usuario pide verificar un CUIT nuevo, aclarale que eso lo hace la
  skill `verificar-proveedores`.
