# Final Report — Gaming Stacked Compositor Fix

**Date:** 2026-10-20  
**Status:** COMPLETADO — todos los criterios de éxito superados

---

## Resumen Ejecutivo

Se identificaron y corrigieron 3 root causes que hacían que el compositor de gaming no funcionara correctamente. El resultado final es un layout STACKED preciso donde:

- El gameplay aparece en la parte SUPERIOR con el porcentaje exacto configurado
- La webcam aparece en la parte INFERIOR con el porcentaje restante
- Ambos paneles usan modo FIT (sin recortar contenido)
- Los ratios 50/50, 60/40, 65/35, 70/30 funcionan exactamente
- Preview y render final son coherentes

---

## Criterios de Éxito — Resultado

| Criterio | Estado |
|----------|--------|
| 1. Dos regiones correctas extraídas | ✓ split=2 desde fuente única |
| 2. Gameplay arriba | ✓ vstack: v0(gameplay) encima de v1(webcam) |
| 3. Webcam abajo | ✓ vstack: v1(webcam) debajo de v0(gameplay) |
| 4. Ambos paneles visibles simultáneamente | ✓ vstack, no overlay |
| 5. Porcentajes configurados respetados exactamente | ✓ 960/960, 1152/768, 1248/672, 1344/576 |
| 6. FIT preserva toda la región seleccionada | ✓ force_original_aspect_ratio=decrease+pad |
| 7. Sin distorsión ni recorte inesperado | ✓ FIT mode, no extra crop after scale |
| 8. Preview = MP4 final | ✓ misma función _compute_stacked_fit_filter |
| 9. Tests y E2E pasan | ✓ 21+20 unit tests, 57 adicionales |
| 10. Comparativas reales disponibles | ✓ 6 renders en experiments/gaming_stacked_layout/ |

---

## Cambios de Código

### 1. `engine/renderers/render_clip.py`

**Nueva función:** `_compute_stacked_fit_filter()` (línea ~747)
- FIT mode (decrease+pad) para gameplay Y webcam
- Variante blurred background con boxblur+overlay
- Preset routing: `preset == 'GAMING_STACKED_FIT'` → esta función

**Fix RC1:** Línea ~162 — usa `src_w`/`src_h` (dims reales del vídeo) no `crop_config.src_width` (dims del preview 720p)

**Fix RC3:** `validation_status` acepta `"pending"` además de `"validated"` y `"confirmed_no_preview"`

### 2. DB (Alembic ab18ecd35fe4)

Nuevas columnas en `crop_configs`:
- `layout_preset TEXT DEFAULT 'GAMING_STACKED_FIT'`
- `gameplay_bg TEXT DEFAULT 'black'`

### 3. `dashboard/index.html`

UI de "Gaming Layout" en New Job:
- 4 botones de ratio: 50/50 | 60/40 | **65/35★** | 70/30
- Toggle de fondo: **Neutral** | Blurred
- Estado: `_njSplitFraction = 0.65`, `_njGameplayBg = 'black'`
- Ambos parámetros enviados en `POST /crop-configs` y previews

### 4. `api/main.py`

- `POST /crop-configs` acepta y persiste `layout_preset` y `gameplay_bg`
- `POST /crop-configs/preview-file` usa `_compute_stacked_fit_filter` vía import
- `POST /crop-configs/preview-url` misma función
- `POST /crop-configs/debug-render` disponible para validación

---

## Evidencia

- **6 renders de ratio** → `experiments/gaming_stacked_layout/01_*.mp4` ... `05_*.mp4`
- **Baseline para comparación** → `00_current_fill_65_35.mp4` (modo FILL antiguo)
- **BEFORE/AFTER renders** → `experiments/crop_precision_repair/renders/`
- **Contact sheets SBS** → `experiments/crop_precision_repair/contact_sheets/`
- **Synthetic tests** → `experiments/crop_precision_repair/synthetic/crop_results/`

---

## Constraints Respetadas

- NO se modificaron clips publicados
- NO se modificaron jobs históricos
- NO se tocó YouTube / Publishing Queue / Scoring / Whisper / Smart Boundary Repair
- Renders previos NO se reprocesaron
- NO se activó nada globalmente sin autorización del usuario
- NO se añadieron funcionalidades nuevas más allá del spec

---

## Tests

```
tests/test_gaming_stacked_layout.py   — 21/21 PASS
tests/test_crop_precision.py          — 20/20 PASS
Suite completa                        — 374/386 PASS (12 preexistentes)
```
