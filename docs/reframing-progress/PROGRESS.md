# Reframing Progress — Smart Reframe Encargo

Última actualización: 2026-10-09

---

## Fase 1: Inspección y reproducción (COMPLETADA)

### Estado del sistema antes de correcciones

- `candidates` con `framing_plan != NULL`: ~400 / 1240
- Clips usando center crop (sin plan): ~95
- Clips con `fallback=True`: 3

### Clips fallidos identificados y reproducidos

| Clip | Creator | Intervalo | Error | Gravedad |
|---|---|---|---|---|
| `8634b3fb` | illojuan | 1067.3–1103.4s | x=136 (background face) vs real x≈792 | SEVERO |
| `228e3717` | mrbeast | 283.6–321.4s | confianza baja (0.30), off-center | LEVE |
| `f050c48a` | anita_rqp | 246.0–282.8s | sujeto desplazado a derecha | LEVE |

### Causa raíz: `illojuan` (caso severo)

MediaPipe BlazeFace detectaba **caras falsas de fondo** (34–44px de ancho en proxy, área 1156–1936 px²) que aparecían en 53 de 73 frames. La cara real de IlloJuan (136–323px, área 18000–140000 px²) solo era detectada en 17 frames cuando miraba a cámara.

El EMA (α=0.25) + mediana sobre todos los offsets producía x=136 en vez de x≈792.

Caras de fondo encontradas:
- Objeto decorativo/pantalla en la pared izquierda (~x=30–65 en proxy 640x360)
- Nunca representan al sujeto principal del vídeo

---

## Corrección implementada: `_MIN_FACE_AREA_FRAC`

**Archivo**: `engine/reframe/planner.py`

**Cambio**: Añadida constante `_MIN_FACE_AREA_FRAC = 0.01` (1% del área del frame proxy).
En el bucle de detección, las caras con `fw * fh < proxy_w * proxy_h * 0.01` se descartan antes de pasar al ByteTracker.

**Umbral efectivo** para proxy 640×360: 2304 px²
- Caras de fondo: 1156–1936 px² → FILTRADAS
- Cara real de IlloJuan: 18000–140000 px² → CONSERVADAS

**Resultado tras corrección**:

| Clip | Antes | Después | Mejora |
|---|---|---|---|
| illojuan `8634b3fb` | x=136, conf=0.96 (FALSO) | x=792, conf=0.34 | CORRECTO |
| mrbeast `228e3717` | x=570, conf=0.63 | x=682, conf=0.30 | Mejor |
| anita_rqp `f050c48a` | x=738, conf=0.93 | x=759, conf=0.88 | Estable |

Frames de referencia guardados en `docs/reframing-progress/frames/`.

---

## Fase 2: Pendiente — Clips de test (24 clips anotados)

- 12 clips dev con anotaciones editoriales
- 12 clips reservados para validación final

## Fase 3: COMPLETADA — Columna `framing_plan` en `clips`

Migración Alembic `0007_a720229ca710`: añadida `clips.framing_plan TEXT`. Aplicada y en producción. HEAD de Alembic en este estado.

Nota: 0 clips tienen `framing_plan` aceptado (la UI existe pero ningún usuario ha aceptado un reframe todavía).

## Fase 4: COMPLETADA — Endpoint de re-render con nuevo framing

`POST /clips/{id}/accept-reframe-variant` — implementado en `api/main.py`. Persiste el `framing_plan` aceptado en `clips.framing_plan` y re-renderiza el clip.

## Fase 5: COMPLETADA — UI de framing en dashboard

Pestaña "Reframe" en el modal de clip: vista before/after, estado PENDING/ACCEPTED/REJECTED, botón aceptar/rechazar, badge de estado.

## Fase 6: Pendiente — Tests automatizados y validación

- Tests de coordenadas (letterbox, scale mapping)
- Tests de escenas (boundary detection)
- Validación en set de 24 clips
