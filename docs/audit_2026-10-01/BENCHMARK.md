# Pipeline Benchmark — 2026-10-01

Datos reales de `pipeline_timings` (10 jobs, todos COMPLETED).  
Unidades: segundos. `—` = etapa no ejecutada (proxy cacheado, series_detection opcional).

## Datos por Job

| Job | Fecha | Transcr. | Proxy | Visual | Candid. | Render | QA | Total | Clips |
|---|---|---|---|---|---|---|---|---|---|
| 10f6ea51 | 2026-09-12 | 274.4 | 38.6 | 24.4 | 0.9 | 98.7 | 0.7 | 440.2 | 10 |
| ce61a112 | 2026-09-15 | 414.4 | 59.1 | 34.2 | 1.2 | 99.0 | 0.7 | 611.9 | 10 |
| e8c1fcf5 | 2026-09-15 | 2050.2 | 163.0 | 30.7 | 3.8 | 97.7 | 0.7 | 2349.3 | 10 |
| b6d1df00 | 2026-09-16 | 1211.3 | — | 17.5 | 0.1 | 34.3 | 0.3 | 1265.4 | 5 |
| 1ad8fae3 | 2026-09-22 | **43495.2** | 280.7 | 51.3 | 0.3 | 132.6 | 0.8 | 46370.1 | 20 |
| 4e877428 | 2026-09-23 | 987.2 | 132.2 | 39.5 | 0.3 | 139.2 | 1.1 | 1302.6 | 10 |
| 60dec872 | 2026-09-23 | 1608.3 | 284.2 | 14.1 | 0.1 | 76.4 | 0.3 | 1984.9 | 5 |
| bc14b63c | 2026-09-23 | 158.6 | 321.9 | 13.2 | 0.9 | 123.4 | 0.6 | 621.0 | 10 |

## Estadísticas Agregadas (todas las etapas, n=10 runs cada una salvo series_detection n=4)

| Etapa | n | Avg (s) | Mediana (s) | Min (s) | Max (s) |
|---|---|---|---|---|---|
| transcription | 10 | 5254.9 | 1099.3 | 105.2 | 43495.2 |
| proxy_generation | 10 | 128.9 | 97.9 | 0.0 | 321.9 |
| render_all_clips | 10 | 95.2 | 99.9 | 23.5 | 139.2 |
| visual_and_audio_analysis | 10 | 27.5 | 27.6 | 13.2 | 51.3 |
| skills | 10 | 1.6 | 1.8 | 0.5 | 2.3 |
| candidate_detection | 10 | 0.8 | 0.6 | 0.1 | 3.8 |
| qa_and_gate | 10 | 0.6 | 0.7 | 0.2 | 1.1 |
| platform_fit | 10 | 0.3 | 0.3 | 0.1 | 0.4 |
| virality_scoring | 10 | 0.2 | 0.2 | 0.1 | 0.3 |
| series_detection | 4 | 0.2 | 0.2 | 0.2 | 0.3 |
| ingest | 10 | 0.1 | 0.1 | 0.1 | 0.2 |

## Distribución de tiempo (sin outlier 1ad8fae3)

Con los 7 jobs "normales" (total < 2400s):

| Etapa | % tiempo promedio |
|---|---|
| transcription | 73.4% |
| proxy_generation | 10.0% |
| render_all_clips | 8.7% |
| visual_and_audio_analysis | 2.5% |
| resto (7 etapas) | 5.4% |

## Notas

- **job 1ad8fae3 (xbuyer):** Outlier extremo. Transcripción de 37 min de vídeo en español devolvió 0 palabras tras 12+ horas. Causa: audio de música dominante + habla en español difícil para faster-whisper sin parámetro `language`. Los 20 clips existen pero sin captions.
- **job b6d1df00:** proxy_generation = 0s porque el proxy ya estaba cacheado del job previo del mismo vídeo.
- **render por clip:** Total render / clips = ~10-14s por clip (single FFmpeg pass: trim+crop+ASS).
- **Hardware encoding:** QSV/NVENC detectado según `hw_accel.py`; fallback libx264 veryfast si no disponible.
