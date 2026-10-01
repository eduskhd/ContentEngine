# Mejoras Priorizadas — 2026-10-01

Backlog priorizado por impacto en pipeline funcional. P0 = bloquea uso real; P1 = degradación significativa; P2 = mejora de calidad; P3 = nice-to-have.

---

## P0 — Bloquean output utilizable

### P0-01: Transcripción vacía en audio difícil
**Síntoma:** faster-whisper devuelve 0 palabras para vídeos en español con música/ruido. El job completa sin error pero los clips quedan sin captions.  
**Causa raíz:** No se pasa `language` ni se usa VAD agresivo. El modelo dedica tiempo al silencio y la música.  
**Fix propuesto:**
- Detectar idioma del creador desde `creator_slug` / metadatos y pasar `language="es"` a `model.transcribe()`  
- Activar `vad_filter=True` en faster-whisper para filtrar segmentos sin voz  
- Si `len(words) == 0` tras transcripción → loguear advertencia y marcar video con `transcription_quality=failed` para reintento  
**Archivos:** `engine/transcription.py`  
**Esfuerzo:** S (1-2h)

### P0-02: 12 publicaciones en estado `failed`
**Síntoma:** 12 filas en `publications` con status='failed'. Clips válidos no publicados.  
**Causa raíz:** No investigada en esta sesión. Probablemente sesiones de upload expiradas.  
**Fix propuesto:** Auditar con `SELECT pub_id, error_message FROM yt_upload_sessions WHERE status='error'` y reintentar vía batch endpoint.  
**Esfuerzo:** S (30 min investigación)

---

## P1 — Degradación significativa de UX

### P1-01: Video duplicado en retry de pipeline
**Estado:** CORREGIDO (ingest.py dedup por job_id+path)  
**Seguimiento:** El duplicado preexistente (xbuyer) sigue en DB. Para limpiarlo: `DELETE FROM videos WHERE id='0b744b82-...' AND id NOT IN (SELECT video_id FROM candidates)` — pero los candidates referencian ambos IDs, así que se requiere un script de merge.

### P1-02: Analysis tab — datos no previstos al abrir
**Síntoma:** El selector de job arranca vacío. No hay carga automática del job más reciente.  
**Fix propuesto:** En `showTab('analysis')`, auto-seleccionar el job más reciente de la lista y cargar su análisis.  
**Archivos:** `dashboard/index.html`  
**Esfuerzo:** XS (30 min)

### P1-03: Jobs CLIPS column (completado)
**Estado:** CORREGIDO (ver INFORME_AUDITORIA.md §BUG-02)

---

## P2 — Calidad y robustez

### P2-01: Detección de idioma automática para transcripción
**Descripción:** Antes de llamar a faster-whisper, inferir idioma desde `creator_slug` o metadatos del vídeo y pasar `language=` explícitamente. Reduce probabilidad de transcripción vacía y mejora velocidad (el modelo no necesita detectar idioma).  
**Archivos:** `engine/transcription.py`  
**Esfuerzo:** S

### P2-02: Re-run de transcripción desde UI
**Descripción:** Botón "Re-transcribir" en el panel de análisis de un job/vídeo. Permite forzar re-transcripción sin crear un nuevo job (reutilizando el archivo descargado).  
**Archivos:** `api/main.py` (endpoint nuevo), `dashboard/index.html`  
**Esfuerzo:** M (3-4h)

### P2-03: Reencuadre centrado en hablante
**Descripción:** El crop actual toma el centro del frame. Para vídeos con un hablante en cámara, añadir detección de cara (MediaPipe Face Detection, ligero) para centrar el crop horizontalmente.  
**Archivos:** `engine/renderers/render_clip.py`  
**Esfuerzo:** L (1-2 días, requiere dependencia nueva)

### P2-04: Verificación de captions post-render
**Descripción:** Tras render, comprobar que el clip tiene palabras visibles (ASS no vacío). Si `words==[]`, marcar `caption_burned=false` en DB y avisar en UI.  
**Archivos:** `engine/renderers/render_clip.py`, `engine/database.py`  
**Esfuerzo:** S

### P2-05: Umbral PUBLISH ajustable por creador
**Descripción:** El 72.5% de clips en REVIEW indica umbral muy bajo para marcado automático PUBLISH. Permitir configurar `publish_threshold` por `creator_id`.  
**Archivos:** `engine/config.py`, `engine/analyzers/virality_predictor.py`  
**Esfuerzo:** S

---

## P3 — Nice-to-have

### P3-01: Auto-selección de job en Analysis tab
Ver P1-02. Pequeño pero visible.

### P3-02: Indicador de calidad de transcripción en Library
**Descripción:** Badge "sin captions" en clips de vídeos con `words_json='[]'`.

### P3-03: Estadísticas de publicación reales en Stats tab
**Descripción:** El tab Stats es stub. Para activarlo, `analytics/collector.py` necesita implementación real (YouTube Data API: views, likes, comments por video_id).  
**Esfuerzo:** L (depende de YouTube API quota)

### P3-04: Limpiar duplicado xbuyer de DB
**Descripción:** Script one-time para merger candidates/series del video 0b744b82 → 17430a89 y borrar el registro duplicado.  
**Esfuerzo:** S (script aislado, requiere backup previo)

---

## Resumen por esfuerzo

| Esfuerzo | Items |
|---|---|
| XS (< 30 min) | P1-02 |
| S (1-4h) | P0-01, P0-02, P2-01, P2-04, P2-05, P3-04 |
| M (medio día) | P2-02 |
| L (> 1 día) | P2-03, P3-03 |
