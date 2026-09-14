# ContentEngine — Lista de Tareas Priorizadas
**Fecha:** 2026-09-14  
**Vinculado a:** PRODUCT_STRATEGY_2026-09-14.md

---

## Categorías de prioridad

| Categoría | Criterio |
|---|---|
| **A — Crítico** | Bloquea la monetización o cierra la brecha competitiva más visible |
| **B — Alto** | Mejora sustancial de valor o abre segmento de mercado |
| **C — Medio** | Mejora de calidad o experiencia, no bloqueante |
| **D — Bajo** | Nice-to-have, puede esperar a V2 |
| **E — Descartar / Postponer** | No prioritario ahora; riesgo > beneficio en esta fase |

---

## A — Crítico (hacer primero)

### A-001 — Face tracking para reencuadre automático
- **Impacto:** Cierra la brecha más visible frente a OpusClip, Klap, Riverside
- **Qué hacer:** Integrar MediaPipe Face Detection (o YOLOv8-face) en `engine/renderers/render_clip.py`. Calcular x_offset medio del segmento (no frame a frame) para evitar latencia excesiva.
- **Criterio de éxito:** Sujeto centrado en >80% de clips con speaker visible
- **Esfuerzo estimado:** 2-3 semanas
- **Dependencias:** MediaPipe o ultralytics instalado localmente
- **Riesgo:** Latencia añadida. Mitigación: sampling cada N frames, no por frame.

### A-002 — Auth básica + multi-workspace
- **Impacto:** Permite vender licencias a equipos. Sin esto no hay modelo de negocio para >1 usuario.
- **Qué hacer:** API key por workspace en header `X-API-Key`. Middleware en `api/main.py`. Añadir `workspace_id INTEGER DEFAULT 0` a tablas `creators`, `videos`, `jobs`, `clips`. Filtrar todas las queries por workspace_id.
- **Criterio de éxito:** Dos usuarios distintos con API keys distintas no ven los datos del otro
- **Esfuerzo estimado:** 1-2 semanas (incluyendo migración DB y tests manuales)
- **Dependencias:** Ninguna externa
- **Riesgo:** Migración de datos existentes. Mitigación: workspace_id=0 para todos los registros históricos.

### A-003 — Instalador con dependencias bundleadas
- **Impacto:** Elimina la barrera de entrada técnica. Actualmente requiere Python, FFmpeg, faster-whisper y dependencias instalados manualmente.
- **Qué hacer:** Script de instalación para Windows que instale Python venv, descargue FFmpeg, instale requirements.txt, y cree acceso directo. Opcionalmente: PyInstaller bundle o NSIS installer.
- **Criterio de éxito:** Usuario sin conocimientos técnicos puede instalar y abrir el dashboard en <10 minutos
- **Esfuerzo estimado:** 1 semana
- **Dependencias:** Ninguna
- **Riesgo:** Bajo. Principal problema: tamaño del bundle (~2-4 GB con modelos Whisper).

---

## B — Alto (siguiente sprint)

### B-001 — Publicación a YouTube (OAuth real)
- **Impacto:** Cierra el loop completo: ingest → clips → publish. YouTube es la plataforma con API más estable y menos restrictiva.
- **Qué hacer:** Activar el adaptador `publishers/youtube.py`. Configurar OAuth 2.0 con Google Cloud Console. Añadir UI en dashboard para autenticar y publicar.
- **Criterio de éxito:** Clip marcado como APPROVED se puede publicar a YouTube Shorts en 1 click
- **Esfuerzo estimado:** 2 semanas
- **Dependencias:** Google Cloud Console project + OAuth credentials
- **Riesgo:** Cambios en la API de YouTube. Mitigación: versionar el adaptador.

### B-002 — Scoring mejorado para contenido en español
- **Impacto:** Abre el mercado hispanohablante. Los word banks de virality scorer y los prompts LLM están en inglés.
- **Qué hacer:** Expandir `engine/analyzers/virality_scorer.py` con word banks en español. Adaptar el prompt LLM en `engine/analyzers/llm_analyzer.py` para detectar idioma y ajustar el análisis.
- **Criterio de éxito:** Clips en español tienen scores comparables a clips en inglés equivalentes
- **Esfuerzo estimado:** 3-5 días
- **Dependencias:** Ninguna externa
- **Riesgo:** Bajo.

### B-003 — Dashboard: indicador LLM enabled/disabled
- **Impacto:** KI-011 documentado. Los usuarios no saben si el scoring LLM está activo.
- **Qué hacer:** Añadir `llm_enabled: bool` a `GET /health`. Mostrar badge en dashboard: "LLM: ON / OFF".
- **Criterio de éxito:** Al arrancar sin ANTHROPIC_API_KEY, el dashboard muestra "LLM: desactivado"
- **Esfuerzo estimado:** 2-3 horas
- **Dependencias:** Ninguna
- **Riesgo:** Ninguno.

### B-004 — Retranscripción de clips sin caption_data
- **Impacto:** KI-003 documentado. Clips viejos sin word timestamps no pueden usar el caption editor.
- **Qué hacer:** Endpoint `POST /clips/{id}/retranscribe`. Re-ejecuta transcripción para la ventana de tiempo del clip y guarda word data.
- **Criterio de éxito:** Clips pre-caption recuperan caption_data funcional sin re-procesar el vídeo completo
- **Esfuerzo estimado:** 1 día
- **Dependencias:** Ninguna
- **Riesgo:** Bajo.

### B-005 — Clasificación de errores retryable vs permanente
- **Impacto:** KI-010. Vídeos con formato inválido se reintentan 3 veces desperdiciando tiempo.
- **Qué hacer:** Añadir categoría de error a `jobs` table. Clasificar errores en pipeline: RETRYABLE (red, OOM) vs PERMANENT (formato, codec). Jobs PERMANENT no se reintentan.
- **Criterio de éxito:** Un vídeo .txt renombrado como .mp4 falla en 1 intento, no en 3
- **Esfuerzo estimado:** 3-5 días
- **Dependencias:** Ninguna
- **Riesgo:** Bajo.

---

## C — Medio (backlog activo)

### C-001 — Deduplicación de URLs en submit
- **Impacto:** KI-007. Doble-click o dos tabs crean dos jobs completos.
- **Qué hacer:** En `POST /jobs/from-url`, consultar `jobs` por `source_path` antes de crear. Si existe job running o completed para misma URL, devolver ese job_id.
- **Esfuerzo estimado:** 2-3 horas
- **Riesgo:** Ninguno.

### C-002 — Column allowlist en update_* helpers de database.py
- **Impacto:** KI-SEC-002. Prevención proactiva de SQLi si se añaden endpoints sin filtrar.
- **Qué hacer:** En `engine/database.py`, añadir allowlist de columnas dentro de cada función `update_*` antes de construir el query.
- **Esfuerzo estimado:** 2-4 horas
- **Riesgo:** Bajo. Tests manuales de las rutas existentes tras el cambio.

### C-003 — Benchmark de face tracking vs crop centrado
- **Impacto:** Valida A-001 antes de integrar en producción.
- **Qué hacer:** Ejecutar protocolo de benchmarks del documento de estrategia con V1 (crop centrado) y V2 (face tracking). Evaluar calidad subjetiva + latencia.
- **Esfuerzo estimado:** 1-2 días
- **Riesgo:** Ninguno. Es investigación, no implementación.

### C-004 — Preset de captions adicional: minimalista
- **Impacto:** Los 3 presets actuales (impact/aura/glowing_bold) son todos de alta energía. Contenido corporativo o educativo necesita preset sobrio.
- **Qué hacer:** Añadir preset `minimal` en `engine/captions/presets.py`: texto blanco, sin highlight animado, fuente sans-serif, tamaño moderado.
- **Esfuerzo estimado:** 2-3 horas
- **Riesgo:** Ninguno.

### C-005 — Logging de LLM costs en pipeline_timings
- **Impacto:** No hay visibilidad del coste real de la API de Anthropic por job.
- **Qué hacer:** Añadir `llm_tokens_used INT`, `llm_cost_usd REAL` a `pipeline_timings`. Loguear desde `llm_analyzer.py`.
- **Esfuerzo estimado:** 3-4 horas
- **Riesgo:** Ninguno.

---

## D — Bajo (ideas para V2)

### D-001 — Publicación a TikTok e Instagram
- **Nota:** TikTok Content Posting API requiere solicitud de acceso oficial. Instagram Graph API requiere cuenta Business y aprobación Meta. Activar solo cuando haya demanda real de un cliente.
- **Esfuerzo estimado:** 2-3 semanas por plataforma

### D-002 — App web accesible desde red local (con auth)
- **Nota:** Solo tiene sentido tras A-002 (auth). Implica cambiar `host="127.0.0.1"` a configurable + reverse proxy.
- **Esfuerzo estimado:** 1 semana + infraestructura

### D-003 — Soporte de batch: procesar carpeta completa de vídeos
- **Nota:** Útil para agencias. Requiere UI para drag-and-drop de múltiples archivos y cola visible.
- **Esfuerzo estimado:** 1-2 semanas

### D-004 — Exportación a Notion / Google Sheets de métricas de clips
- **Nota:** Solicitado por creadores que trackean performance. No prioritario hasta tener publicación social funcional.
- **Esfuerzo estimado:** 3-5 días

### D-005 — Migración a PostgreSQL
- **Nota:** Solo necesario si se supera 10 usuarios concurrentes o la base de datos supera 10GB. SQLite WAL es suficiente hasta entonces.
- **Esfuerzo estimado:** 2-3 semanas (incluyendo migración de datos)

---

## E — Descartar / Postponer

### E-001 — Analytics post-publish (`analytics/collector.py`)
- **Motivo:** Stub sin publicación social funcional activa. Inútil hasta que D-001 esté completo y haya datos reales.

### E-002 — Sistema de aprendizaje / autopsy (`learning/autopsy.py`)
- **Motivo:** Requiere datos de engagement real de redes sociales. Sin publicación activa, no hay datos. Postponer hasta V3.

### E-003 — OAuth multi-plataforma completo
- **Motivo:** Alta complejidad de mantenimiento, APIs cambian frecuentemente, restricciones de acceso de TikTok. Empezar solo con YouTube (B-001).

### E-004 — Refactoring de código existente que funciona
- **Motivo:** Instrucción explícita del proyecto: "Never delete, rewrite, or refactor working code unless it directly blocks the pipeline." Los renderers legacy (`clip_generator.py`, `reframer.py`, `caption_burner.py`) siguen en uso por el endpoint de re-render.

---

## Resumen ejecutivo de prioridades

```
AHORA (1-6 semanas):     A-001 Face tracking
                          A-002 Auth + multi-workspace
                          A-003 Instalador

PRÓXIMO SPRINT:           B-001 YouTube publish
                          B-002 Español scoring
                          B-003 LLM indicator (trivial)
                          B-005 Error classification

BACKLOG ACTIVO:           C-001 URL dedup (trivial)
                          C-002 Column allowlist (seguridad)
                          C-003 Benchmark face tracking

V2 (post-primeros clientes): D-001 TikTok/Instagram
                              D-002 Red local
                              D-003 Batch processing

NO TOCAR AHORA:           E-001 Analytics
                          E-002 Autopsy
                          E-004 Refactoring
```
