# Manual Crop — Recovery & Completion Status

Fecha: 2026-10-20

| Componente | Estado | Evidencia | Próximo paso |
|---|---|---|---|
| Preparación del vídeo (POST /jobs/prepare-preview) | COMPLETE_VERIFIED | 7/7 frames extraídos en 6.8s, probado con URL real | — |
| Extracción de frames (yt-dlp + ffmpeg) | COMPLETE_VERIFIED | Formato bestvideo[height<=720]/bestvideo/best corregido; cache 1h | — |
| Galería de fotogramas | COMPLETE_VERIFIED | 7 thumbnails con timestamps, scroll horizontal, frame extra por timestamp | — |
| Selector gameplay (amarillo) | COMPLETE_VERIFIED | PointerEvents: draw, move, resize; coordenadas normalizadas [0-1] | — |
| Selector facecam (verde) | COMPLETE_VERIFIED | Idem; ambas regiones coexisten sin interferencia | — |
| Coordenadas normalizadas | COMPLETE_VERIFIED | Coord display en tiempo real: "GP: 0.020,0.020 0.750×0.800 \| CAM: ..." | — |
| Preservación al cambiar fotograma | COMPLETE_VERIFIED | Prueba 4: regiones iguales antes/después de njGallerySelectFrame(2) | — |
| Overlay en galería | COMPLETE_VERIFIED | njRedrawGallery() dibuja rects en todos los thumbnails al modificar | — |
| Preview 50/50 FFmpeg | COMPLETE_VERIFIED | /crop-configs/preview-url genera MP4 en ~8s; video en panel | — |
| Confirmación crop | COMPLETE_VERIFIED | njUrlConfirmCrop() → badge visible → submit habilitado | — |
| Integración con Job | COMPLETE_VERIFIED | njSubmit envía gameplay_rect/facecam_rect a POST /crop-configs | — |
| Render FFmpeg (renderer) | COMPLETE_VERIFIED | _compute_split_layout_filter_manual usa rects normalizadas → píxeles | — |
| Cache de stream URL | COMPLETE_VERIFIED | _preview_stream_cache reutilizado en /url-frame, /prepare-preview, /preview-url | — |
| Modo automático no roto | COMPLETE_VERIFIED | njSetCropMode('automatic') oculta panel, submit sigue funcionando | — |
| Reset de regiones | COMPLETE_VERIFIED | njUrlResetRegions() pone gameplay/facecam a null | — |

## Bugs corregidos durante la sesión

1. **Formato yt-dlp** — `best[height<=720]/best` fallaba para vídeos sin formato combinado; cambiado a `bestvideo[height<=720]/bestvideo/best` en los tres endpoints.
2. **Cache no compartida** — `/crop-configs/preview-url` usaba yt-dlp propio; ahora usa `_preview_stream_cache` compartida.
3. **gameplay_rect dict vs lista** — endpoint de preview esperaba lista, JS mandaba dict; corregido con `_normalise_rect()`.
4. **Preview button sin estado disabled visible** — CSS añadido: `.nj-btn-preview:disabled`.
5. **Thumbnail en canvas** — Eliminado `njUrlLoadThumbnail()` / `njUrlLoadFrame()`; canvas solo carga frames reales de galería.
6. **Colores spec** — gameplay=amarillo (#facc15), facecam=verde (#22c55e) según especificación.
