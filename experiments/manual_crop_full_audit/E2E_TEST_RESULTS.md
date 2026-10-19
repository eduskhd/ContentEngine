# E2E Test Results — Manual Crop Selector

Fecha: 2026-10-20  
URL de prueba: https://www.youtube.com/watch?v=1WEAJ-DFkHE (MrBeast, 10:31, 1280×720)

## Prueba 1 — Fotogramas reales del vídeo

**Resultado: PASS**

- Panel "Gaming Crop Setup" aparece correctamente debajo de Video Type / Crop Setup
- Click "▶ Prepare Video Preview" → llamada a POST /jobs/prepare-preview
- 7/7 frames extraídos en 6.8s (con cache yt-dlp reutilizada)
- Timestamps: 0:32, 1:35, 3:09, 5:16, 7:22, 8:57, 10:03 (5%–95% de 631s)
- No se usa thumbnail en el canvas. Evidencia: `img.getAttribute('src') === ''` hasta que se selecciona frame de galería

## Prueba 2 — Selector gameplay + move + resize

**Resultado: PASS**

- Click "Select Gameplay Region" (botón amarillo) activa drawMode='gameplay'
- Drag en canvas → rect amarillo aparece con label "GAMEPLAY" y 8 handles
- Move: gameplay.x aumentó de 0.020 a 0.120 después de arrastrar desde centro
- Resize SE: facecam.w aumentó de 0.230 a 0.310 después de arrastrar esquina
- Coordenadas mostradas en tiempo real bajo el canvas

## Prueba 3 — Selector facecam

**Resultado: PASS**

- Click "Select Camera Region" (botón verde) activa drawMode='facecam'
- Drag en canvas → rect verde aparece con label "CAMERA"
- Ambas regiones visibles simultáneamente, sin interferencia

## Prueba 4 — Preservación al cambiar fotograma

**Resultado: PASS**

- Antes de cambiar: `{gameplay: {x:0.02, y:0.02, w:0.75, h:0.80}, facecam: {x:0.76, y:0.02, w:0.23, h:0.33}}`
- Después de `njGallerySelectFrame(2)`: idéntico
- Preserved: true

## Prueba 5 — Preview 50/50

**Resultado: PASS**

- Click "Preview 50/50 (5s)" → POST /crop-configs/preview-url
- Formato yt-dlp corregido (bestvideo[height<=720])
- MP4 generado en ~8s, disponible en /static/previews/{uuid}.mp4
- Video aparece en panel de preview dentro del modal
- `_njUrlPreviewValidated = true`

## Prueba 6 — Confirm + Create Job

**Resultado: PASS**

- Click "✓ Confirm Crop Setup" → `_njUrlCropConfirmed = true`
- Badge "✓ Crop confirmed — ready to create job" visible
- Submit button habilitado con texto "Create Job"
- Al submitir: POST /jobs + POST /crop-configs (con validation_status='validated')

## Prueba 7 — Overlay en galería (verificación cross-frame)

**Resultado: PASS**

- Después de dibujar regiones, todos los thumbnails de la galería muestran las rects superpuestas
- njRedrawGallery() se llama desde njUrlRedrawCanvas() en cada cambio
- Frame seleccionado tiene borde verde; resto borde transparente (azul al hover)

## Prueba 8 — Modo automático no roto

**Resultado: PASS**

- `njSetCropMode('automatic')` → panel Gaming Crop Setup desaparece
- Auto crop notice visible
- Submit habilitado sin necesitar confirmación de crop
- `njSetCropMode('manual')` → panel reaparece

## Prueba 9 — Reset de regiones

**Resultado: PASS**

- `njUrlResetRegions()` → `_njUrlCropState = {gameplay: null, facecam: null}`
- Canvas se limpia
- Preview button se deshabilita
- `_njUrlCropConfirmed = false`

## Prueba 10 — Console y errores

**Sin errores críticos en consola.** Bugs detectados y corregidos:
1. Format string yt-dlp (3 endpoints)
2. Cache no compartida en preview-url
3. gameplay_rect dict→lista normalización
4. CSS disabled para Preview button
5. Dead code eliminado (njUrlLoadThumbnail, njUrlLoadFrame)
6. Colores corregidos (amarillo/verde)
