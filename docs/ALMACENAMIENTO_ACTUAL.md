# Almacenamiento Actual — ContentEngine

Estado medido el 2026-09-18. Actualiza con `GET /storage/summary` o el botón "Actualizar" en Settings → Almacenamiento.

## Rutas principales

| Recurso | Ruta |
|---|---|
| Base de datos | `C:\Users\edupo\Desktop\ContentEngine\db\engine.sqlite` |
| Directorio output | `C:\Users\edupo\Desktop\ContentEngine\output` |
| Tokens YouTube | `C:\Users\edupo\.contentengine\yt_tokens.json` |
| Credenciales OAuth | `.env` (raíz del proyecto, excluido de Git) |

## Tamaños medidos (2026-09-18)

| Subdirectorio | Tamaño | Descripción |
|---|---|---|
| `output/downloads` | ~1 775 MB | Vídeos originales descargados (8 archivos) |
| `output/mrbeast` | ~499 MB | Slug de creador: archivos de vídeo MrBeast |
| `output/audio` | ~225 MB | Archivos WAV extraídos para transcripción |
| `output/proxies` | ~159 MB | Proxies 360p 2fps para análisis visual |
| `output/kai_cenat_live` | ~127 MB | Slug de creador: archivos Kai Cenat |
| `output/clips` | — | Clips renderizados (con captions ASS) |
| `output/thumbnails` | — | Miniaturas generadas |
| **Total output** | **~3 155 MB** | |
| Base de datos | ~8 MB | WAL mode, incluye todos los índices |
| **Disco libre** | **~357 GB** | Partición C: |

## Archivos faltantes conocidos

| Tipo | ID (parcial) | Ruta |
|---|---|---|
| Vídeo | `drafteados_ms8…` | `output/downloads/drafteados_ms8nxjbhfki.mp4` |

El archivo fue probablemente borrado manualmente. La entrada en la tabla `videos` permanece. Causa que el job aparezca como procesable pero falle si se reintenta.

## Contenido de la base de datos (2026-09-18)

| Tabla | Registros |
|---|---|
| videos | 4 |
| candidates | 108 |
| clips | 46 |
| publications | 16 |
| yt_upload_sessions | 1 |
| jobs | ~20 |

## Estructura de directorios de output

```
output/
  downloads/        ← vídeos descargados vía yt-dlp
  uploads/          ← vídeos subidos manualmente
  audio/            ← WAV para faster-whisper / HF Whisper
  proxies/          ← 360p 2fps para análisis visual
  clips/            ← clips renderizados (trim+crop+caption en un paso)
  thumbnails/       ← miniaturas para el dashboard
  <creator-slug>/   ← directorio por creador (slug de la URL)
```

## Sistema de backup

**No hay backup automatizado.** Los archivos de vídeo originales son los únicos activos críticos no reproducibles (los clips se pueden re-renderizar desde la DB + proxies).

### Opciones para el futuro

1. **R2/B2/S3** — subir `output/downloads` a almacenamiento cloud cuando el job se complete.
   - Candidato: `publishers/r2_storage.py` (por crear)
   - Hook en `engine/pipeline.py` al final del paso INGEST
2. **Script robocopy local** — copia incremental a disco externo o NAS.
   - `robocopy output D:\Backup\ContentEngine\output /MIR /R:2 /W:5`
3. **Alerta de espacio** — ya implementada: si `free_gb < 1`, `server.py` falla en arranque.

## API de almacenamiento

```
GET  /storage/summary   → desglose detallado + archivos faltantes
POST /storage/scan      → re-escaneo rápido de presencia de archivos
```

Disponible en Settings → Almacenamiento del dashboard.
