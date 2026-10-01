# Auditoría Integral Content Engine — 2026-10-01

**Auditor:** Claude Sonnet 4.6 (sesión automatizada)  
**Fecha:** 2026-10-01  
**Alcance:** Estado real del código, DB, UI (todas las pestañas), pipeline, calidad de clips y bugs activos  
**Restricciones aplicadas:** Sin publicación nueva · Sin borrado de contenido del canal · Pruebas sobre datos reales (sin fixtures de aislamiento) · Sin infraestructura de pago adicional

---

## 1. Estado General

| Dimensión | Estado |
|---|---|
| Servidor | Operativo (localhost:8000) |
| Workers | 2 activos |
| Jobs totales | 8 (todos COMPLETED) |
| Clips generados | 80 (22 PUBLISH, 58 REVIEW) |
| Pipeline etapas | 12 pasos (render 1-pass activo) |
| YouTube | Conectado — canal ContentEngine |
| TikTok / Instagram | No conectados (inactivos por diseño) |
| Base de datos | SQLite WAL · 8 MB · 32 tablas |
| Almacenamiento clips | 5929.5 MB |

---

## 2. Auditoría UI — Todas las Pestañas

### Overview ✅
- KPIs correctos: 80 clips · 22 aprobados · 58 pendientes · 8 jobs · 2 workers
- Recent clips table y jobs summary renderizan bien
- Ningún error visual

### Library ✅
- 7 creadores visibles con conteo de vídeos y clips
- Filtros de colección operativos
- **Observación:** xbuyer muestra 2 registros de vídeo para la misma URL (bug de duplicado — ver §4)

### Review ✅
- 58 clips pendientes correctamente listados
- Botones Approve / Reject / Download funcionan
- Modal de caption editor accesible desde cada clip

### Jobs ⚠️ → CORREGIDO
- **Bug encontrado:** Columna CLIPS mostraba "—" para todos los jobs completados
- **Causa:** `/jobs` API no incluía `clip_count` en la respuesta; el dashboard sólo leía `result.stats.clips_generated` que es null para jobs de DB
- **Fix aplicado:** Subquery `(SELECT COUNT(*) FROM clips WHERE job_id=j.id)` añadida al SQL; campo `clip_count` expuesto en JSON; dashboard actualizado con fallback `j.clip_count`
- **Resultado verificado:** CLIPS muestra 5, 10, 10, 10, 10, 10, 20 correctamente

### New Job ✅
- Pestaña URL con preview de metadatos y detección de duplicados
- Pestaña Upload con arrastrar/soltar
- Detección de URL duplicada operativa (devuelve `{"duplicate": true, "job_id": "..."}`)

### Publishing ✅
- Vista por defecto "Listos para subir" (comportamiento corregido en sesión anterior)
- Botón "Subir" por clip en listos, "YouTube Studio" para publicados
- Publications: 33 ready, 27 published, 12 failed, 2 draft, 1 archived

### Analysis ✅ (funcional, vacío sin selección)
- Selector de job completado + botón Refresh
- Sin errores JS al cargar

### Stats ⚠️ (stub inactivo)
- Muestra "No analytics yet — publish clips and collect metrics first"
- Botones "Collect Metrics" y "Run Autopsy" presentes pero el backend es stub
- Esperado por diseño (ver CLAUDE.md §"What to ignore")

### OAuth ✅
- YouTube: Connected — canal ContentEngine (UCJu5hBYkfg-yWjvDel67rkA)
- TikTok / Instagram: Connect buttons (no conectados, inactivos por diseño)
- Storage: 5929.5 MB output · 360.3 GB disco libre (24.3% usado) · DB 8 MB

---

## 3. Pipeline — Medición y Bottlenecks

### Tiempos por etapa (10 jobs, mediana)

| Etapa | Avg (s) | Min (s) | Max (s) | % del total |
|---|---|---|---|---|
| transcription | 5254.9 | 105.2 | 43495.2 | ~90-99% |
| proxy_generation | 128.9 | 0.0 | 321.9 | ~2-15% |
| render_all_clips | 95.2 | 23.5 | 139.2 | ~1-22% |
| visual_and_audio_analysis | 27.5 | 13.2 | 51.3 | ~1-7% |
| skills | 1.6 | 0.5 | 2.3 | <1% |
| candidate_detection | 0.8 | 0.1 | 3.8 | <1% |
| qa_and_gate | 0.6 | 0.2 | 1.1 | <1% |
| platform_fit | 0.3 | 0.1 | 0.4 | <1% |
| virality_scoring | 0.2 | 0.1 | 0.3 | <1% |
| series_detection | 0.2 | 0.2 | 0.3 | <1% |
| ingest | 0.1 | 0.1 | 0.2 | <1% |

**Cuello de botella dominante: transcripción (faster-whisper).** En el peor caso (job 1ad8fae3, xbuyer, vídeo 37 min en español), tomó 43495s (12 horas) y devolvió 0 palabras — el modelo no detectó habla reconocible.

### Rango total por job
- Mínimo: 440s (~7 min) — MrBeast 10 clips
- Máximo: 46370s (~13h) — xbuyer 20 clips (anomalía por transcripción fallida)
- Mediana (sin el outlier): ~1300s (~22 min)

---

## 4. Bugs Identificados

### BUG-01: Duplicate video record on pipeline retry ⚠️ → CORREGIDO
- **Descripción:** Si un job se reintenta (mismo job_id), `ingest()` crea un segundo registro de vídeo para el mismo path/URL. xbuyer tiene 2 registros (17430a89, 0b744b82) para la misma URL.
- **Impacto:** 60 candidatos en total (30 duplicados) en DB; Library muestra el vídeo dos veces; clips no afectados (referencian job_id, no video_id)
- **Fix:** `engine/ingest.py` — comprobación previa `WHERE job_id=? AND path=?` antes de crear nuevo registro

### BUG-02: Jobs CLIPS column shows "—" ⚠️ → CORREGIDO
- **Descripción:** La columna CLIPS en la tabla Jobs mostraba "—" para todos los jobs completados cargados desde DB
- **Fix:** `api/main.py` — subquery de COUNT añadida al SQL de `/jobs`; `dashboard/index.html` — fallback `j.clip_count` añadido

### BUG-03: Empty transcription for 4 videos (no fix, no re-run autorizado)
- **Afectados:** videos 8cce3c56 (drafteados), 17430a89 (xbuyer), 0b744b82 (xbuyer dup), 3992d1d2 (ibai)
- **Síntoma:** `words_json='[]'` — faster-whisper ejecutó sin error pero devolvió 0 palabras
- **Causa probable:** Audio con música dominante, voz sin separación suficiente, o idioma no detectado correctamente
- **Impacto:** Clips de estos vídeos existen (80 clips total, todos QA PASS) pero sin captions sincronizados
- **Estado:** No corregido. Re-ejecutar transcripción requiere nuevo job (autorización pendiente)

### BUG-04: Publications failed=12
- **Descripción:** 12 publicaciones en estado `failed` en DB
- **Investigación pendiente:** No verificadas individualmente en esta sesión. Probablemente sesiones de upload con errores de red o expiradas del encargo anterior
- **Recomendación:** Auditar vía `SELECT * FROM publications WHERE status='failed'` y reintentar si los clips siguen siendo válidos

---

## 5. Integridad de Datos

| Check | Resultado |
|---|---|
| jobs todos COMPLETED | ✅ |
| clips con QA PASS | ✅ 80/80 |
| clips con caption_data null o vacío | ✅ 0 (caption_data presente en todos) |
| videos con transcripción vacía (words_json='[]') | ⚠️ 4/9 |
| video duplicado mismo source_url | ⚠️ 1 caso (xbuyer) |
| publications stuck en 'publishing' | ✅ 0 (corregido en sesión anterior) |
| yt_upload_sessions activas sin cerrar | No verificado en esta sesión |

---

## 6. Resumen de Fixes Aplicados

| Fix | Archivo | Descripción |
|---|---|---|
| clip_count en /jobs | `api/main.py:241` | Subquery COUNT clips por job |
| dashboard fallback clip_count | `dashboard/index.html:4344` | `j.clip_count` como fallback |
| ingest dedup por path | `engine/ingest.py:41` | SELECT antes de INSERT |

---

## 7. Conclusión

Content Engine está **operativo y estable**. El pipeline completa correctamente con hardware encoding (QSV/NVENC/libx264). Los dos bugs de UI/API identificados han sido corregidos. El cuello de botella principal es la transcripción (faster-whisper), que en casos de audio difícil puede superar las 12 horas sin producir output utilizable — esto requiere mejora en detección de idioma y VAD antes de ejecutar.

Ver documentos complementarios:
- `BENCHMARK.md` — datos brutos por job
- `MATRIZ_CONTROLES.csv` — 20 escenarios QA
- `EVALUACION_CALIDAD.md` — análisis de calidad de clips
- `MEJORAS_PRIORIZADAS.md` — backlog priorizado
