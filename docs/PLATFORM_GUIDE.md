# ContentEngine — Guía Interna de la Plataforma

> Documento de referencia completo. Cubre qué hace la plataforma, cómo está construida, cómo se usa, qué contiene cada fichero y cómo extenderla sin romper nada.

---

## Índice

1. [¿Qué es ContentEngine?](#1-qué-es-contentengine)
2. [Arrancar el servidor](#2-arrancar-el-servidor)
3. [El dashboard — guía de uso](#3-el-dashboard--guía-de-uso)
4. [Flujo completo paso a paso](#4-flujo-completo-paso-a-paso)
5. [Pipeline técnico (12 pasos)](#5-pipeline-técnico-12-pasos)
6. [Sistema de Creadores (Library)](#6-sistema-de-creadores-library)
7. [Sistema de Captions](#7-sistema-de-captions)
8. [Sistema de Análisis Viral](#8-sistema-de-análisis-viral)
9. [Base de datos — tablas y relaciones](#9-base-de-datos--tablas-y-relaciones)
10. [API REST — endpoints completos](#10-api-rest--endpoints-completos)
11. [Workers y cola de trabajos](#11-workers-y-cola-de-trabajos)
12. [Ficheros y estructura del proyecto](#12-ficheros-y-estructura-del-proyecto)
13. [Configuración](#13-configuración)
14. [Decisiones de arquitectura](#14-decisiones-de-arquitectura)
15. [Lo que está desactivado (y por qué)](#15-lo-que-está-desactivado-y-por-qué)
16. [Cómo extender la plataforma](#16-cómo-extender-la-plataforma)
17. [Problemas conocidos y limitaciones](#17-problemas-conocidos-y-limitaciones)

---

## 1. ¿Qué es ContentEngine?

**ContentEngine** es una herramienta privada de clipping de vídeo con IA.

El flujo es:

```
Vídeo largo (URL o fichero local)
        ↓
Pipeline automático de 12 pasos
        ↓
Clips de 9:16, listos para publicar
con captions karaoke sincronizadas
y score de viralidad
```

**No es** un producto público. Es una herramienta personal para procesar contenido de creadores y generar clips cortos (TikTok / Reels / Shorts) de forma automática.

### Capacidades actuales

- Descarga vídeos de YouTube, TikTok, Instagram u otras fuentes compatibles con yt-dlp
- Transcribe con faster-whisper (timestamps palabra a palabra)
- Detecta los mejores momentos mediante análisis semántico heurístico (sin LLM)
- Genera clips recortados, reencuadrados a 9:16 y con captions quemadas
- Organiza el contenido por **Creador → Vídeos → Clips / Series**
- Asigna scores de viralidad con 9 componentes y razones explicativas
- Detecta secuencias narrativas y las divide en partes (series)

### Lo que NO hace (desactivado por diseño)

- Publicar en TikTok, Instagram o YouTube (el código existe pero no se usa)
- Recoger métricas de engagement post-publicación
- Gestionar múltiples usuarios o cuentas

---

## 2. Arrancar el servidor

```powershell
cd C:\Users\edupo\Desktop\ContentEngine
python server.py
```

El servidor arranca en `http://localhost:8000`.

Rutas principales:
- **Dashboard**: `http://localhost:8000/dashboard`
- **API docs**: `http://localhost:8000/docs`
- **Health check**: `http://localhost:8000/health`

### Opciones de arranque

```powershell
python server.py              # 2 workers (por defecto)
python server.py 4            # 4 workers
python server.py --workers 4  # equivalente
```

### Qué pasa al arrancar

1. `init_db()` — crea tablas si no existen, añade columnas nuevas (seguro de repetir)
2. Se ejecuta la migración de creadores (linkea vídeos existentes a creators)
3. `WorkerPool(n)` — crea n hilos daemon que pollan la cola cada 2 segundos
4. `uvicorn` sirve la API en el puerto 8000

---

## 3. El dashboard — guía de uso

El dashboard es una SPA (Single Page Application) en `dashboard/index.html`. No usa frameworks externos — vanilla JS.

### Tabs de navegación

| Tab | Función |
|-----|---------|
| **Overview** | Estadísticas globales + clips recientes |
| **Library** | Biblioteca de vídeos organizada por Creador |
| **Clips** | Cola de revisión de todos los clips generados |
| **Jobs** | Tabla de todos los trabajos (completados e histórico) |
| **Analysis** | Análisis de viralidad de un trabajo específico |
| **+ New Job** | Subir vídeo o pegar URL para procesar |
| **Analytics** | Métricas de engagement (stub, inactivo) |
| **OAuth** | Conexión de cuentas sociales (inactivo) |

### Library — cómo funciona

La Library es **creator-first**: la vista principal muestra tarjetas de creador. Al entrar en un creador se ven sus vídeos con thumbnails, status, score y clips.

**Navegación en la sidebar:**
- All Creators — grid con todas las tarjetas de creador
- All Videos — lista completa con filtros
- Processing — trabajos activos en este momento
- Failed — trabajos fallidos (con botón Retry)
- Lista de creadores — acceso directo a cada carpeta
- Unassigned — vídeos sin creador asignado

**Acciones disponibles:**

| Acción | Cómo |
|--------|------|
| Entrar en un creador | Clic en la tarjeta |
| Marcar favorito | ★ en la tarjeta del creador |
| Crear nuevo creador | "+ New Creator" en la sidebar o modal |
| Editar creador | Botón "Edit" en la cabecera del creador |
| Seleccionar vídeos | Botón "Select" → checkboxes en cada tarjeta |
| Asignar creador en bulk | Select → "Assign Creator" |
| Borrar en bulk | Select → "Delete" → confirmar |
| Borrar individual | Icono 🗑 en la tarjeta del vídeo |
| Mover a otro creador | "Move Creator" bajo cada tarjeta |
| Ver análisis del vídeo | Clic en tarjeta → abre pestaña Analysis |
| Reintentar un job fallido | Vista Failed → "Retry" |

**Confirmación de borrado:**
Al borrar siempre aparece un modal con dos opciones:
- **Videos only** — elimina el registro pero no los clips en disco
- **Videos + Clips** — borrado en cascada (candidatos, clips, ficheros MP4)

### + New Job — cómo procesar un vídeo

1. Pegar URL de YouTube/TikTok/Instagram **o** hacer clic en la zona de fichero para subir local
2. Seleccionar **Creator** (buscable; si no existe, "+ Create New Creator" lo crea inline)
3. Elegir número de clips (3, 5, 10, 20 o AUTO)
4. Seleccionar plataformas objetivo (TikTok, Instagram, YouTube)
5. Pulsar **Start Processing**

El trabajo aparece inmediatamente con una barra de progreso y se actualiza en tiempo real via SSE.

### Clips — revisión y descarga

En la pestaña **Clips** aparecen todos los clips generados. Para cada clip:

- **▶ Play** — abre el modal con player + editor de captions
- **✓ Approve / ✕ Reject** — cambia la decisión de publicación
- **↓ Download** — descarga el MP4 con captions quemadas

El modal de player tiene tres pestañas:
- **Style** — preset (Impact / Aura / Glowing), tamaño, colores, animación
- **Words** — editar texto de cada palabra sin cambiar los timestamps
- **Position** — arriba / centro / lower third + margen exacto

Al hacer cambios en el editor → **Save style** guarda las preferencias → **Re-render MP4** vuelve a quemar las captions con la nueva configuración.

### Analysis — análisis de viralidad

1. Seleccionar un job completado en el desplegable
2. Ver los candidatos ordenados por **Virality Score** con etiquetas de razones
3. Ver las series detectadas con sus partes
4. **Generate Top 3/5/10** — renderiza los N mejores candidatos que aún no tienen clip
5. **Generate Best Series** — renderiza todos los clips de la mejor serie detectada

---

## 4. Flujo completo paso a paso

### Caso típico: vídeo de YouTube con audio

```
1. Pegar URL (ej: youtube.com/watch?v=...)
2. Seleccionar creator (ej: "MrBeast")
3. Elegir 5 clips
4. Start Processing

→ El job aparece en cola (chip "queued")
→ El worker lo recoge y arranca el pipeline

INGEST       Descarga con yt-dlp, extrae creator/título del canal
TRANSCRIBE   faster-whisper → lista de palabras con timestamps (ej: 3.200 palabras)
CANDIDATES   Detecta 12-20 ventanas candidatas usando análisis semántico
VISUAL       Analiza calidad visual en cada ventana (OpenCV)
AUDIO        Mide energía de audio en cada ventana (librosa)
PLATFORM FIT Calcula adecuación por plataforma
VIRALITY     Ensemble score de 9 componentes, genera razones, importance_score
SERIES       Agrupa candidatos adyacentes en series narrativas (si aplica)
SKILLS       hook_analyzer + virality_predictor (log a skill_runs)
CLIP GEN     ffmpeg corta los 5 mejores clips
REFRAME      ffmpeg encuadra cada clip a 1080×1920 (9:16)
CAPTIONS     Extrae palabras por timestamp → ASS karaoke → quema con ffmpeg
QA/GATE      Verifica resolución, duración, audio → PUBLISH / REVIEW / REJECT

→ chip cambia a "completed"
→ Banner de notificación "5 clips listos"
→ Los clips aparecen en Clips para revisar
```

### Caso: upload local (sin audio)

El pipeline detecta automáticamente que no hay stream de audio con ffprobe. En ese caso:
- Transcripción devuelve `[]` (lista vacía)
- Candidate detection usa scoring posicional (segmentos al principio del vídeo puntúan más)
- Captions no se generan (no hay palabras)
- El resto del pipeline continúa normalmente

---

## 5. Pipeline técnico (12 pasos)

El pipeline completo está en `engine/pipeline.py → process_video()`.

### Paso 1 — INGEST (`engine/ingest.py`)

- Si la fuente es una URL: `download_url()` con yt-dlp, extrae título, creator, platform, channel ID
- Si es un fichero local: copia a `output/uploads/`
- Crea el registro `video` en la BD con duration, fps, width, height
- Lee `jobs.creator_id` y lo asigna al vídeo (`assign_video_creator`)

### Paso 2 — TRANSCRIPTION (`engine/transcription.py`)

- `_has_audio_stream()` con ffprobe — si no hay audio, devuelve `[]`
- Primary: `faster-whisper` modelo `base.en` (inglés), word_timestamps=True
- Fallback: `openai-whisper` si faster-whisper falla
- Devuelve lista de dicts: `[{word, start, end}, ...]`
- El transcript completo se guarda en `videos.transcript` (texto plano)

### Paso 3 — CANDIDATE DETECTION (`engine/analyzers/candidate_detector.py`)

1. **Sentence segmentation**: agrupa palabras en frases por pausas >0.4s y puntuación
2. **Semantic scoring** por frase: hooks, emoción, story markers, standalone value
3. **Peak detection**: encuentra frases de alto score
4. **Context expansion**: expande cada peak para incluir setup + payoff
5. **Smart boundaries**: `find_smart_start()` y `find_smart_end()` buscan pausas naturales
6. **IoU deduplication**: elimina ventanas que se solapan >50%
7. Fallback posicional cuando no hay palabras

Cada candidato se guarda con: start_s, end_s, score, emotion_score, retention_score, importance_score, hook_time, virality_reasons, smart_start, smart_end.

### Paso 4 — VISUAL ANALYSIS (`engine/analyzers/visual_analyzer.py`)

- OpenCV procesa frames del vídeo
- Detecta cortes de escena (diferencia de histograma)
- Mide intensidad de movimiento (diferencia inter-frame)
- Detecta presencia de caras (cascade classifier)
- Asigna `visual_score` a cada candidato

### Paso 5 — AUDIO ANALYSIS (`engine/analyzers/audio_analyzer.py`)

- librosa carga el audio extraído
- Calcula energía RMS por ventana
- Detecta música vs voz
- Asigna `audio_score` a cada candidato
- Omitido si no hay stream de audio

### Paso 6 — PLATFORM FIT (`engine/analyzers/platform_fit.py`)

- Evalúa cada candidato contra los requisitos de cada plataforma
- TikTok: duración 15-60s, aspect ratio 9:16 ideal
- Instagram: duración 15-90s
- YouTube Shorts: duración <60s
- Guarda `platform_scores` como JSON en candidates

### Paso 7 — VIRALITY SCORING (`engine/analyzers/virality_scorer.py`)

Fórmula de ensemble de 9 componentes:

| Componente | Peso | Fuente |
|-----------|------|--------|
| semantic_interest | 20% | semantic_analyzer |
| hook_strength | 20% | hook_score de candidate |
| emotional_intensity | 15% | emotion_score |
| standalone_value | 10% | standalone_value signal |
| audio_energy | 10% | audio_score |
| visual_reaction | 10% | visual_score |
| payoff_strength | 5% | payoff signal |
| shareability | 5% | semantic signals |
| short_form_fit | 5% | duración + platform_scores |

Outputs por candidato:
- `virality_score` (0-100) — potencial viral
- `importance_score` (0-100) — relevancia dentro del vídeo original
- `retention_score` (0-100) — hook_time + pacing + dead_air + progression
- `virality_reasons` — lista de strings explicativos (ej: "Strong hook opener", "High emotional intensity")

**Score tiers:**
- 90-100 → Exceptional 🔴
- 80-89 → High Potential 🟠
- 70-79 → Good 🟡
- 60-69 → Average 🟢
- <60 → Low ⚫

### Paso 7.5 — SERIES DETECTION (`engine/analyzers/series_detector.py`)

- Agrupa candidatos adyacentes (distancia <120s entre sí)
- Si el arco total supera 60s, lo convierte en serie
- Divide en 2-4 partes de ~30s cada una
- Guarda en tabla `clip_series` con series_score y reasons
- Candidatos actualizados con `series_id` y `series_part`

### Paso 8 — SKILLS (`engine/skills_integration.py`)

- `hook_analyzer` — analiza el hook del clip
- `virality_predictor` — segunda pasada de predicción
- Resultados guardados en `skill_runs` (solo para logs)

### Paso 9 — CLIP GENERATION (`engine/renderers/clip_generator.py`)

```bash
ffmpeg -y -ss {start_s} -t {duration} -i {source} -c copy {output_path}
```

- Usa `-c copy` para velocidad máxima (sin re-encode)
- Output en `output/{creator_slug}/{video_slug}/clip_{n}.mp4`

### Paso 10 — REFRAME 9:16 (`engine/renderers/reframer.py`)

```bash
ffmpeg -y -i {clip} -vf "crop={h}:{h}:{cx}:0,scale=1080:1920" {output}
```

- Crop cuadrado centrado (o centrado en cara si se detecta)
- Scale a 1080×1920
- Re-encode con libx264 para garantizar compatibilidad

### Paso 11 — CAPTION BURN-IN (`engine/renderers/caption_burner.py`)

1. `extract_clip_words()` — filtra las palabras del transcript que caen en el rango del clip, normaliza timestamps a t=0
2. `build_ass()` — genera fichero ASS con eventos karaoke por palabra
3. `ffmpeg -vf "ass='file.ass'"` — quema los subtítulos en el vídeo

El fichero quemado se guarda en `clips.captioned_path`.

### Paso 12 — QA + PRE-PUBLISH GATE

**QA técnica** (`engine/qa/video_qa.py`):
- Resolución ≥ 1080×1920
- Duración entre 10s y 65s
- FPS ≥ 24
- Tamaño de fichero > 10 KB
- Tiene stream de audio

**QA visual:**
- Duración ≥ 10s
- Tamaño de fichero > 50 KB

**Gate (FAIL CLOSED):**
- `technical_qa=FAIL` OR `visual_qa=FAIL` → `prepublish_decision=REJECT`
- Ambos PASS → `prepublish_decision=PUBLISH`
- Un check WARN (no crítico) → `prepublish_decision=REVIEW`

---

## 6. Sistema de Creadores (Library)

### Concepto

Cada **Creator** representa un canal o creador de contenido. Un vídeo pertenece a un creator. Los clips heredan el creator del vídeo.

```
Creator (MrBeast)
    └── Video (Stream #42)
            ├── Clip 1 — 96/100
            ├── Clip 2 — 91/100
            └── Serie Argumento
                    ├── Parte 1 — 31s
                    ├── Parte 2 — 28s
                    └── Parte 3 — 30s
```

### Tabla `creators`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| id | TEXT PK | UUID |
| name | TEXT | Nombre canónico (ej: "MrBeast") |
| display_name | TEXT | Nombre para mostrar (puede ser igual) |
| handle | TEXT | @handle o username |
| avatar_color | TEXT | Color CSS para el placeholder del avatar |
| platform | TEXT | Plataforma principal (youtube, tiktok...) |
| channel_url | TEXT | URL del canal |
| external_channel_id | TEXT | ID del canal en la plataforma |
| is_favorite | INTEGER | 0/1 — aparece primero en la grid |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |

### Asignación de creator a un vídeo

1. **Al crear el job** — el usuario selecciona un creator en el formulario
2. El `creator_id` se guarda en `jobs.creator_id`
3. Durante el pipeline (paso INGEST) → se copia a `videos.creator_id`
4. **Post-proceso** — desde la Library se puede reasignar con "Move Creator"

**Vídeos sin creator** (`creator_id IS NULL`) aparecen en la carpeta **Unassigned**.

### Migración de datos existentes

Al arrancar el servidor, `_migrate_creators()` procesa todos los vídeos con `creator_id=NULL`:
- Lee `job.creator` (nombre de texto libre introducido al crear el job)
- Normaliza (title-case si todo minúsculas)
- Busca creator existente por nombre (case-insensitive)
- Si no existe: crea uno nuevo con `avatar_color` generado por hash del nombre
- Actualiza `videos.creator_id` y `jobs.creator_id`
- No crea creators para nombres vacíos o valores genéricos ("unknown", "local", "")

### Deduplicación

La creación de creators via `POST /creators` hace:
```sql
SELECT id FROM creators WHERE name=? COLLATE NOCASE
```
Si ya existe, devuelve el ID existente en lugar de crear un duplicado.

La migración también usa COLLATE NOCASE. Sin embargo, si el mismo creador fue introducido con variantes muy distintas ("MrBeast" vs "Mr Beast") pueden quedar dos registros — en ese caso usar "Move Creator" para reasignar los vídeos al creator correcto y borrar el duplicado.

---

## 7. Sistema de Captions

### Formato ASS (Advanced SubStation Alpha)

Los captions usan ASS, no SRT. ASS permite:
- Timing por palabra individual (no por grupo)
- Colores distintos por palabra (highlight de la palabra activa)
- Override de escala por palabra (efecto "pop")

**Color ASS**: `&HAABBGGRR` (alpha invertido, bytes en orden BGR — lo opuesto a HTML)
- `&H00FFFFFF` = blanco opaco
- `&H0000FFFF` = amarillo opaco (highlight por defecto)

### Presets disponibles

| Preset | Icono | Estilo |
|--------|-------|--------|
| impact | ⚡ | Blanco con stroke negro, highlight amarillo |
| aura | ✨ | Gradiente suave, efecto glow |
| glowing_bold | 🔥 | Bold, borde naranja, highlight rojo |

### Flujo de captions

```
words (lista de {word, start, end})
    ↓ extract_clip_words(all_words, clip_start, clip_end)
    → normaliza timestamps a t=0 dentro del clip
    ↓ build_ass(words, settings, width=1080, height=1920)
    → genera string ASS con un evento por palabra
    ↓ ffmpeg -vf "ass='temp.ass'"
    → clip con captions quemadas → captioned_path
```

### Caption data en BD

- `clips.caption_data` — JSON: `{words:[{word,start,end},...], has_audio, clip_start, clip_end}`
- `clips.caption_settings` — JSON: preset, font_size, text_color, highlight_color, stroke_width, animation, position, margin_v, uppercase, max_words

### Editor de captions en el dashboard

El modal de player incluye un editor en tiempo real:
- Preview en canvas (no requiere re-render)
- Edición de palabras individuales sin cambiar timestamps
- Posición: arriba / centro / lower third + margen custom
- "Re-render MP4" → llama a `POST /clips/{id}/re-render` con las settings guardadas

---

## 8. Sistema de Análisis Viral

### Semantic Analyzer (`engine/analyzers/semantic_analyzer.py`)

Análisis heurístico puro — sin LLM, sin APIs externas.

**Hook patterns** (50+):
Frases que típicamente abren clips virales ("wait for it", "you won't believe", "plot twist", "breaking news", preguntas directas, etc.)

**Emotion word banks**:
- excitement: "incredible", "amazing", "insane", "unbelievable"...
- surprise: "unexpected", "plot twist", "suddenly", "wait"...
- tension: "problem", "failed", "worst", "crisis"...
- humor: "hilarious", "ridiculous", "absurd"...
- conflict: "fight", "argue", "vs", "battle"...
- revelation: "revealed", "secret", "truth", "exposed"...

**Story structure markers**:
- setup: "so basically", "here's what happened", "the reason"...
- escalation: "then", "but then", "suddenly", "that's when"...
- peak: "and then", "finally", "at this point"...
- payoff: "which means", "turns out", "in the end"...

**Smart cut boundaries**:
- `find_smart_start()` — busca pausa >0.4s en ventana de ±12s antes del target
- `find_smart_end()` — busca pausa >0.4s y fin de frase en ±12s después del target

### Retention Score

Compuesto de:
- `hook_time`: tiempo hasta la primera palabra fuerte (menor = mejor)
- `pacing`: palabras por segundo (óptimo ~2.5-3.5 wps)
- `dead_air`: porcentaje de silencio (penaliza pausas excesivas)
- `progression`: variación de energía a lo largo del clip (monotonía = penalización)

Devuelto en escala 0-100.

### Virality Reasons

Cada candidato recibe una lista de strings que explican por qué puntúa alto:
- "Strong hook opener" — empieza con patrón de hook
- "High emotional intensity" — emotion_score > 0.7
- "Optimal duration" — entre 20-45s
- "Story arc complete" — tiene setup + peak + payoff
- "High audio energy" — audio_score > 0.75
- etc.

---

## 9. Base de datos — tablas y relaciones

```
creators
    │ 1:N
    ├── videos (via creator_id)
    │       │ 1:N
    │       ├── candidates (via video_id)
    │       │       │ 1:1
    │       │       └── clips (via candidate_id)
    │       │               └── prepublish_decisions
    │       │               └── publish_log
    │       └── clip_series (via video_id)
    │               │ (series_id en candidates)
    └── jobs (via creator_id)
            └── job_queue (payload contiene job_id y source)
            └── skill_runs
```

### Tabla `jobs`

| Campo | Descripción |
|-------|-------------|
| id | UUID — mismo que el job_id en `_jobs` dict |
| source_path | Ruta local al vídeo original |
| status | QUEUED / INGESTING / TRANSCRIBING / ANALYZING / RENDERING / QA / COMPLETED / FAILED |
| mode | REVIEW (por defecto) o AUTO |
| target_clips | Número de clips pedidos (0 = AUTO) |
| target_platforms | JSON array ["tiktok","instagram",...] |
| creator | Nombre de texto libre del creador |
| creator_id | FK a creators.id (puede ser NULL) |
| content_type | educational, entertainment, etc. |
| created_at, updated_at | ISO timestamps |
| error | Mensaje de error si status=FAILED |
| metadata | JSON para datos extra |

### Tabla `videos`

| Campo | Descripción |
|-------|-------------|
| id | UUID |
| job_id | FK a jobs |
| path | Ruta local al fichero de vídeo |
| duration_s | Duración en segundos |
| fps, width, height, size_bytes | Propiedades técnicas |
| rights_verified | Siempre 1 (ver D-009) |
| transcript | Texto plano del transcript |
| audio_path | Ruta al WAV extraído para análisis |
| creator_slug | Slug del creador (ej: "mrbeast") |
| video_slug | Slug del vídeo (ej: "dqw4w9wgxcq") |
| source_url | URL original |
| source_platform | youtube / tiktok / instagram / local |
| source_title | Título del vídeo |
| creator_id | FK a creators.id (NULL = Unassigned) |
| thumbnail_path | Ruta al JPEG del thumbnail (generado lazy) |

### Tabla `candidates`

Cada candidato es una ventana de tiempo propuesta para ser clip.

| Campo | Descripción |
|-------|-------------|
| id | UUID |
| job_id, video_id | FKs |
| start_s, end_s | Rango en segundos |
| score | Score bruto inicial |
| virality_score | Score final de viralidad (0-100) |
| importance_score | Relevancia dentro del vídeo (0-100) |
| retention_score | Capacidad de retención (0-100) |
| emotion_score | Intensidad emocional (0-1) |
| hook_score, visual_score, audio_score | Scores por componente |
| hook_time | Tiempo hasta primer hook (segundos) |
| virality_reasons | JSON array de strings |
| smart_start, smart_end | Boundaries ajustadas a pausas naturales |
| series_id | FK a clip_series.id (si pertenece a una serie) |
| series_part | Número de parte dentro de la serie |

### Tabla `clips`

| Campo | Descripción |
|-------|-------------|
| id | UUID |
| job_id, candidate_id | FKs |
| output_path | Ruta al MP4 recortado y reencuadrado |
| captioned_path | Ruta al MP4 con captions quemadas |
| width, height, fps, duration_s, file_size | Propiedades del clip generado |
| technical_qa | PASS / WARN / FAIL |
| visual_qa | PASS / FAIL |
| qa_notes | JSON con detalles de issues |
| prepublish_decision | PUBLISH / REVIEW / REJECT / PENDING |
| prepublish_score | Score numérico del gate |
| caption_data | JSON: {words, has_audio, clip_start, clip_end} |
| caption_settings | JSON: preset + todos los parámetros de estilo |
| review_notes | Notas de revisión manual |

### Tabla `clip_series`

| Campo | Descripción |
|-------|-------------|
| id | UUID |
| job_id, video_id | FKs |
| series_score | Score de la serie (0-100) |
| total_parts | Número de partes |
| series_reasons | JSON array de razones |
| original_start, original_end | Rango del arco completo en el vídeo |
| title | Título descriptivo de la serie |

---

## 10. API REST — endpoints completos

Base URL: `http://localhost:8000`

### Creadores

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/creators` | Lista todos los creadores con stats |
| POST | `/creators` | Crea un creador (body: name, display_name, handle, platform, channel_url) |
| GET | `/creators/{id}` | Detalle de un creador con best_score, avg_score |
| PUT | `/creators/{id}` | Actualiza campos (name, handle, platform, is_favorite, avatar_color) |
| DELETE | `/creators/{id}?action=unassign` | Elimina el creador; `action=unassign` mueve vídeos a Unassigned, `action=delete_all` borra en cascada |

### Vídeos

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/videos` | Lista vídeos con filtros: creator_id, status, platform, search, sort, limit, offset |
| PATCH | `/videos/{id}/creator` | Asigna/desasigna creator (body: {creator_id: "uuid" o null}) |
| POST | `/videos/bulk-assign` | Asignación en bulk (body: {video_ids: [...], creator_id: "uuid" o null}) |
| DELETE | `/videos/{id}?delete_clips=true` | Elimina vídeo y opcionalmente sus clips |
| POST | `/videos/bulk-delete` | Borrado en bulk (body: {video_ids: [...], delete_clips: bool}) |
| GET | `/videos/{id}/thumbnail` | Sirve o genera el thumbnail JPEG (lazy, via ffmpeg) |

### Jobs

| Método | Path | Descripción |
|--------|------|-------------|
| POST | `/jobs` | Crea job desde upload (multipart: video, clips, platforms, mode, creator, creator_id) |
| POST | `/jobs/from-url` | Crea job desde URL (JSON: url, clips, platforms, mode, creator, creator_id) |
| GET | `/jobs` | Lista todos los jobs (merge DB + in-memory) |
| GET | `/jobs/{id}` | Estado de un job específico |
| GET | `/jobs/{id}/events` | SSE stream de actualizaciones en tiempo real |
| GET | `/jobs/{id}/download-all` | ZIP con todos los clips del job |
| POST | `/jobs/{id}/retry` | Reencola un job con status FAILED |
| GET | `/jobs/{id}/analysis` | Análisis completo: candidatos + series |
| GET | `/jobs/{id}/series` | Series detectadas para el job |
| POST | `/jobs/{id}/generate-top` | Genera top N clips no generados (?n=5) |
| POST | `/jobs/{id}/generate-series/{series_id}` | Genera todos los clips de una serie |

### Clips

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/clips` | Lista clips (?decision=PUBLISH/REVIEW/REJECT, ?limit=50) |
| GET | `/clips/{id}` | Detalle de un clip |
| GET | `/clips/{id}/download` | Descarga el MP4 (prefiere captioned_path) |
| GET | `/clips/{id}/preview` | Sirve el MP4 inline (para player) |
| GET | `/clips/{id}/captions` | Datos de captions y groups calculados |
| PUT | `/clips/{id}/captions` | Actualiza caption_data y/o caption_settings |
| POST | `/clips/{id}/re-render` | Vuelve a quemar captions con settings actuales |

### Revisión

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/review/pending` | Todos los clips para revisión |
| POST | `/review/{id}/approve` | Aprueba un clip (→ PUBLISH) |
| POST | `/review/{id}/reject` | Rechaza un clip (→ REJECT) |

### Captions

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/captions/presets` | Lista todos los presets disponibles |

### Otros

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/health` | Status, mode, version |
| GET | `/workers/stats` | Estado de los workers y cola |
| GET | `/dashboard` | Sirve el HTML del dashboard |

---

## 11. Workers y cola de trabajos

### Arquitectura

```
API recibe job
    ↓ pool.submit(job_id, source, clips, platforms, mode, creator)
    ↓ job_queue.enqueue(payload)

WorkerPool (2 hilos daemon)
    ↓ cada 2s: job_queue.dequeue(worker_id)  ← atómico con UPDATE+RETURNING
    ↓ process_video(...)
    ↓ job_queue.complete(job_id, result) o job_queue.fail(job_id, error)
    ↓ _jobs[job_id] actualizado con resultado
```

### `JobQueue` (`workers/job_queue.py`)

- Tabla SQLite `job_queue`
- `dequeue()` usa `UPDATE ... WHERE id=(SELECT ... LIMIT 1) RETURNING id, payload` — atómico, sin race condition entre workers
- Max 3 intentos por job (`max_attempts=3`)
- `stats()` devuelve conteo por status (queued/running/completed/failed)

### Retry

`POST /jobs/{id}/retry` — solo para jobs en status FAILED:
1. `db.update_job(job_id, status="QUEUED", error=None)` — limpia el error
2. `pool.submit(...)` — reencola el trabajo
3. El worker lo procesa como si fuera nuevo (nota: el video/candidates de antes permanecen en BD)

---

## 12. Ficheros y estructura del proyecto

```
ContentEngine/
├── server.py                    Entrypoint: init_db + WorkerPool + uvicorn
├── engine/
│   ├── config.py                CONFIG singleton (paths, thresholds, scoring weights)
│   ├── database.py              init_db(), todos los helpers CRUD, context manager db()
│   ├── ingest.py                Probe de vídeo con ffprobe, create_video()
│   ├── transcription.py         faster-whisper primary, openai-whisper fallback
│   ├── pipeline.py              process_video(): los 12 pasos
│   ├── downloader.py            yt-dlp wrapper, is_url(), download_url()
│   ├── skills_integration.py   run_all_skills(): hook_analyzer + virality_predictor
│   ├── analyzers/
│   │   ├── candidate_detector.py  Detección semántica de candidatos
│   │   ├── semantic_analyzer.py   Hook patterns, emotion banks, story markers
│   │   ├── visual_analyzer.py     OpenCV: shots, motion, faces
│   │   ├── audio_analyzer.py      librosa: energía, música
│   │   ├── virality_scorer.py     Ensemble de 9 componentes
│   │   ├── platform_fit.py        Scores por plataforma
│   │   ├── hook_analyzer.py       Skill: análisis de hooks
│   │   ├── virality_predictor.py  Skill: predictor secundario
│   │   └── series_detector.py     Agrupación en series narrativas
│   ├── renderers/
│   │   ├── clip_generator.py    ffmpeg cut (-c copy)
│   │   ├── reframer.py          ffmpeg crop+scale a 1080×1920
│   │   └── caption_burner.py    Orquestador: extract → build_ass → ffmpeg burn
│   ├── captions/
│   │   ├── presets.py           3 presets (impact/aura/glowing_bold), default_settings()
│   │   ├── extractor.py         extract_clip_words(), group_words()
│   │   └── renderer.py          build_ass(), burn_captions_ass(), _hex_to_ass()
│   └── qa/
│       ├── video_qa.py          run_qa(): technical + visual checks con ffprobe
│       └── prepublish_gate.py   run_prepublish_gate(): PUBLISH/REVIEW/REJECT
├── api/
│   └── main.py                  FastAPI app, todos los endpoints REST
├── workers/
│   ├── pipeline_worker.py       WorkerPool + PipelineWorker (hilos daemon)
│   └── job_queue.py             SQLite-backed job queue (dequeue atómico)
├── publishers/                  TikTok/Instagram/YouTube adapters (INACTIVOS)
├── analytics/
│   └── collector.py             Stub inactivo
├── learning/
│   └── autopsy.py               Stub inactivo
├── dashboard/
│   └── index.html               SPA dashboard completo (vanilla JS, ~3500 líneas)
├── db/
│   └── engine.sqlite            Base de datos principal (WAL mode)
├── output/                      Directorio de clips generados
│   ├── uploads/                 Ficheros subidos localmente
│   ├── downloads/               Ficheros descargados con yt-dlp
│   ├── audio/                   WAV extraídos para análisis
│   ├── thumbnails/              JPEG de thumbnails de vídeo
│   └── {creator}/{video}/      Clips organizados por creador/vídeo
└── docs/
    ├── PLATFORM_GUIDE.md        Esta guía
    ├── ARCHITECTURE.md          Arquitectura técnica
    ├── CHANGELOG.md             Historial de cambios
    ├── DECISIONS.md             Decisiones técnicas y sus razones
    ├── PROJECT_STATUS.md        Estado actual del pipeline
    ├── ROADMAP.md               Próximos pasos (sin compromisos)
    └── KNOWN_ISSUES.md          Bugs conocidos no críticos
```

---

## 13. Configuración

Todo en `engine/config.py` → singleton `CONFIG`.

### Paths críticos

```python
ffmpeg_path       # ruta a ffmpeg (debe estar en PATH o ruta absoluta)
ffprobe_path      # ruta a ffprobe
output_dir        # directorio de clips (por defecto: ./output)
db_path           # base de datos (por defecto: ./db/engine.sqlite)
```

### Parámetros de pipeline

```python
mode              # "REVIEW" (por defecto) o "AUTO"
min_clip_duration # duración mínima de candidato en segundos
max_clip_duration # duración máxima de candidato
target_clips      # número de clips a generar (sobreescrito por process_video)
finalist_multiplier # multiplicador para ampliar el pool de finalists
```

### Parámetros de análisis semántico

```python
smart_cut_window           # ventana (±s) para buscar boundaries naturales (12s)
deduplicate_iou_threshold  # umbral IoU para eliminar duplicados (0.5)
generate_series            # activar detección de series (True)
min_virality_for_auto      # threshold para AUTO mode (70.0)
target_series_part_duration # duración objetivo por parte de serie (30s)
max_series_parts           # máximo de partes por serie (4)
min_series_total_duration  # mínimo para considerar un arco como serie (60s)
```

### Virality weights

```python
virality_ensemble = ScoringWeights(
    semantic    = 0.20,
    hook        = 0.20,
    emotion     = 0.15,
    standalone  = 0.10,
    audio       = 0.10,
    visual      = 0.10,
    payoff      = 0.05,
    shareability= 0.05,
    short_form  = 0.05,
)
```

---

## 14. Decisiones de arquitectura

Ver `docs/DECISIONS.md` para el detalle completo. Resumen:

| ID | Decisión | Razón |
|----|----------|-------|
| D-001 | SQLite con WAL, no Postgres/Redis | Herramienta privada de un solo nodo; WAL da concurrencia sin servicios externos |
| D-002 | `job_id` unificado (API + DB mismo UUID) | Evitar desync entre sesiones de servidor |
| D-003 | `/jobs` lee DB + overlays in-memory | Persistencia entre reinicios + datos en vivo del worker |
| D-004 | `_has_audio_stream()` antes de ffmpeg | ffmpeg no reporta "sin audio" con suficiente precisión; pre-check con ffprobe es obligatorio |
| D-005 | Scoring posicional para vídeos sin audio | Sin transcript no hay señal semántica; posición temporal es la mejor heurística |
| D-006 | ASS para captions, no SRT | SRT no soporta timing por palabra; ASS permite karaoke con `\c` y `\fscx` |
| D-007 | Color ASS en BGR, no RGB | Formato nativo de ASS: `&HAABBGGRR` (bytes invertidos respecto a HTML) |
| D-008 | QA gate FAIL CLOSED | Falso positivo (publicar mal clip) peor que falso negativo (rechazar buen clip) |
| D-009 | `rights_verified=1` siempre | Herramienta de uso privado; la verificación de derechos bloquearía todo |
| D-010 | Canvas 2 pasadas (stroke → fill) | Un solo pass causa bleeding del stroke sobre palabras adyacentes |
| D-011 | Creator-first Library | Con muchos vídeos, la búsqueda plana es inmanejable; carpetas por creator escala |
| D-012 | Migración de creators en init_db | Idempotente (solo procesa videos con creator_id=NULL); segura de repetir en cada arranque |

---

## 15. Lo que está desactivado (y por qué)

### Publishing social (TikTok / Instagram / YouTube)

**Estado:** Código existe en `publishers/`. Adaptadores completos para las tres plataformas.

**Por qué desactivado:** OAuth no configurado. APIs requieren credenciales que no están en uso. Activar implicaría configurar apps en los developer portals de cada plataforma.

**Para activar en el futuro:**
1. Configurar credenciales en `.env`
2. Completar el flujo OAuth (hay endpoints en `/oauth/` pero no están en uso activo)
3. Cambiar `CONFIG.mode = "AUTO"` para habilitar el endpoint `POST /clips/{id}/publish`

### Analytics (`analytics/collector.py`)

**Estado:** Stub. Las funciones existen pero devuelven datos vacíos.

**Por qué desactivado:** Requiere posts publicados con IDs reales para recoger métricas de engagement. Sin publishing activo, no hay datos.

### Learning / Autopsy (`learning/autopsy.py`)

**Estado:** Stub. Devuelve `{status: "insufficient_data"}` hasta tener 5+ posts con métricas.

**Por qué desactivado:** El sistema de aprendizaje compara virality_score predicho vs engagement real. Sin datos de publicación, no hay correlación que calcular.

---

## 16. Cómo extender la plataforma

### Regla fundamental

**No toques código que funciona** a menos que el cambio lo requiera directamente. Si encuentras un bug que no bloquea el pipeline principal, documéntalo en `docs/KNOWN_ISSUES.md` y sigue.

### Añadir una nueva señal al virality scoring

1. Calcula la señal en `engine/analyzers/semantic_analyzer.py` o en el analyzer correspondiente
2. Inclúyela en `engine/analyzers/virality_scorer.py` ajustando el peso (los pesos deben sumar 1.0)
3. Añade la columna si es necesaria con `_add_column_if_missing` en `init_db()`
4. Documenta el cambio en `DECISIONS.md` y `CHANGELOG.md`

### Añadir un nuevo preset de captions

1. Añadir el dict de settings en `engine/captions/presets.py`
2. Añadir el botón en el dashboard (HTML: `preset-grid` div, JS: `selectPreset()`)

### Añadir un nuevo endpoint de API

1. Escribir la función en `api/main.py`
2. Si necesita acceso a BD, añadir el helper en `engine/database.py`
3. Si añade tabla o columna nueva, usar `CREATE TABLE IF NOT EXISTS` o `_add_column_if_missing` en `init_db()`

### Modificar la base de datos de forma segura

- **Nunca** `ALTER TABLE ... DROP COLUMN` (SQLite tiene soporte limitado)
- **Siempre** usar `_add_column_if_missing(conn, tabla, columna, tipo)` para columnas nuevas
- Para tablas nuevas: `CREATE TABLE IF NOT EXISTS` dentro del `executescript` en `init_db()`
- La migración en `init_db()` es idempotente — puede ejecutarse múltiples veces sin daño

### Reglas para el dashboard

El dashboard es un fichero HTML único con CSS + JS inline. No usa frameworks.

- Todo el JS está en `<script>` al final del `<body>`
- Las funciones de cada tab se llaman desde `loadTab(name)` o directamente desde `showTab()`
- Los modales se activan añadiendo/quitando la clase `open`
- Los colores de chips siguen el patrón `.chip-{STATUS}` (uppercase/lowercase ambos definidos)

---

## 17. Problemas conocidos y limitaciones

### Actuales

| Issue | Impacto | Estado |
|-------|---------|--------|
| Duplicados de creators en migración si mismo creador fue introducido con variantes ("MrBeast" vs "Mr Beast") | Organización | Menor — usar "Move Creator" para consolidar manualmente |
| Los clips no tienen endpoint de filtrado directo por creator_id (el dashboard usa job_ids como proxy) | UI | Menor — funcional pero aproximado |
| Sin virtualización en Library para >200 vídeos (límite por defecto: 50) | Performance | Aceptable para uso actual |
| Thumbnail generation puede fallar en vídeos con codec inusual (AV1 lento) | UX | El dashboard muestra un placeholder en ese caso |
| La vista "Series" del creador no está implementada en la nueva Library | Feature | Series disponibles en la pestaña Analysis |

### Limitaciones por diseño

- **Un solo servidor / un solo nodo** — no hay soporte para múltiples instancias
- **Solo inglés** — el modelo Whisper `base.en` solo funciona con voz en inglés; para otros idiomas cambiar el modelo a `base` o `large` en `engine/transcription.py`
- **Resolución de salida fija** — siempre 1080×1920 (9:16); no configurable por clip en la UI
- **ffmpeg debe estar en PATH** — no hay bundling; debe instalarse en el sistema

### Workarounds activos

- `server.py` fuerza UTF-8 en stdout/stderr antes de importar Rich (necesario en Windows con cp1252)
- `video_qa.py` usa `encoding="utf-8", errors="replace"` en subprocess para evitar crash en títulos con caracteres especiales
- El pipeline envuelve `_print_summary()` en try/except para que errores de encoding no marquen el job como FAILED

---

*Última actualización: 2026-09-09 — Creator Library update*
