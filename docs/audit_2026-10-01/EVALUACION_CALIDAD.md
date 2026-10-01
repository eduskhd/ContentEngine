# Evaluación de Calidad de Clips — 2026-10-01

## Resumen

| Métrica | Valor |
|---|---|
| Total clips generados | 80 |
| QA técnico PASS | 80 / 80 (100%) |
| QA visual PASS | 80 / 80 (100%) |
| Marcados PUBLISH | 22 / 80 (27.5%) |
| Marcados REVIEW | 58 / 80 (72.5%) |
| Con caption_data presente | 80 / 80 (100%) |
| Con transcripción válida | ~60 / 80 (estimado — 5 de 9 vídeos) |
| Publicados en YouTube | 27 clips |

## Distribución de Scores de Publicación

La decisión `prepublish_decision` se establece durante `virality_scoring` y `platform_fit`. Valores posibles: `PUBLISH`, `REVIEW`, `REJECT`.

- `PUBLISH` (score alto, >umbral): 22 clips  
- `REVIEW` (score medio, requiere aprobación manual): 58 clips  
- `REJECT`: 0 clips (todos pasaron QA mínimo)

## Calidad de Captions

**Estado:** `caption_data` presente en 80/80 clips (campo JSON con `{words, has_audio, clip_start, clip_end}`).

Sin embargo, 4 vídeos (xbuyer ×2, drafteados, ibai) tienen `words_json='[]'` en la tabla `videos`. Los clips de estos vídeos tendrán `caption_data.words = []`, lo que significa que el render produjo clips con overlay de subtítulos vacío (sin texto visible).

Clips afectados: job 1ad8fae3 (xbuyer, 20 clips). Los otros vídeos sin transcripción (drafteados/ibai) también generaron clips.

**Nota:** La ausencia de palabras no bloquea el render ni el QA gate (técnico/visual pasa igual). El impacto es únicamente captions vacíos.

## Calidad de Transcripción por Vídeo

| Video ID | Creador | words_json len | Calidad estimada |
|---|---|---|---|
| f6192a0d | mrbeast | 304535 chars | Buena |
| 4482b560 | mrbeast | 463740 chars | Buena |
| 6c0ff441 | búscate_la_vida | 3290513 chars | Buena (muy largo) |
| 22ee3ad8 | thegrefg | 1038713 chars | Buena |
| 0552b9c2 | illojuan | 173452 chars | Buena |
| 8cce3c56 | drafteados | 2 chars (`[]`) | VACÍA |
| 17430a89 | xbuyer | 2 chars (`[]`) | VACÍA |
| 0b744b82 | xbuyer (dup) | 2 chars (`[]`) | VACÍA |
| 3992d1d2 | ibai | 2 chars (`[]`) | VACÍA |

## Calidad de Reencuadre

El pipeline usa un **único paso FFmpeg** que combina: trim + crop/scale a 9:16 + ASS caption burn. El reencuadre toma el centro del frame (no hay detección de cara activa). Los clips de vídeos horizontales (16:9) se recortan al centro vertical.

No se evaluó visualmente ningún clip durante esta sesión (reproducción de vídeo no disponible en el entorno de auditoría).

## Coherencia del Scoring

- `prepublish_score` en DB corresponde a `virality_score × platform_fit` compuesto
- Umbral PUBLISH es configurable en `CONFIG`
- El 27.5% de clips marcados PUBLISH es consistente con el objetivo del pipeline (extraer los mejores momentos)
- Los 58 clips en REVIEW requieren aprobación manual antes de publicar

## Recomendaciones de Calidad

1. **Transcripción vacía:** Re-ejecutar con parámetro `language="es"` explícito para vídeos en español detectados por metadatos del creador
2. **Reencuadre:** Añadir detección de cara simple (MediaPipe o similar) para centrar el crop en el hablante
3. **Caption sync:** Añadir verificación post-render que cuente palabras visibles en los primeros 5 segundos del clip
4. **REVIEW a PUBLISH:** Reducir umbral o mejorar scoring para disminuir la cola de revisión manual (72.5% es alta)
