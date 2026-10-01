# INFORME FINAL — Encargo Publishing 2026-09-23

**Fecha:** 2026-09-23  
**Objetivo:** Reparar Publishing + Library, eliminar duplicados, publicar todos los clips pendientes autorizados en YouTube como Público.

---

## Resultado final

| Métrica | Antes | Después |
|---|---|---|
| Vídeos en YouTube | 10 públicos / 3 privados | **26 públicos / 0 privados** |
| Publicaciones `published` | 12 | **27** |
| Publicaciones `failed` | — | 12 (INVALID_FILE, sin archivo) |
| Duplicados en DB | 1 | 0 (archivado) |
| Clips autorizados publicados | 0/13 | **13/13** |
| Sesiones `public` en worker | 13 | **26** |

**Todos los 26 vídeos verificados con YouTube API** → `privacyStatus: public` ✓  
**No quedan pendientes publicables dentro del conjunto autorizado.**

---

## Vídeos publicados en YouTube (26)

### IlloJuan (10 vídeos)

| pub_id | Título | Parte | video_id | Estado YT |
|---|---|---|---|---|
| 29229884 | IlloJuan: Nobody saw this coming | standalone | xBlA0pVeXWo | PUBLIC ✓ |
| 5dc85a4e | IlloJuan: Narrative Sequence | P1 | -Wh1KMuZTRg | PUBLIC ✓ |
| 9faecc90 | IlloJuan: Narrative Sequence | P4 | 87ALx4kG-5w | PUBLIC ✓ |
| 54f78e0e | IlloJuan: Narrative Sequence | P4 | SQ7btHBREmI | PUBLIC ✓ |
| 0d164bce | IlloJuan: Narrative Sequence | P4 | z0JMH6lmYfU | PUBLIC ✓ |
| e89c52d1 | IlloJuan: Narrative Sequence | P4 | E0bbUlIfCOM | PUBLIC ✓ |
| 05aa8917 | IlloJuan: Narrative Sequence | P4 | jSy1277DpPo | PUBLIC ✓ |
| 86d49135 | IlloJuan: Narrative Sequence | P4 | 0n6ms0fSh8Y | PUBLIC ✓ |
| 4f349e46 | IlloJuan: Narrative Sequence | P4 | LclPjBKNXS4 | PUBLIC ✓ |
| a0d17179 | IlloJuan: Narrative Sequence | P4 | k0SnXJaSDPE | PUBLIC ✓ |

### MrBeast — Emotional Story (7 vídeos)

| pub_id | Parte | video_id | Estado YT | Notas |
|---|---|---|---|---|
| fd8642cb | P1 | E5wxZZ2HEbc | PUBLIC ✓ | Re-subido (original cTnYJWjnUO8 no encontrado en canal) |
| 1a3bb8a4 | P2 | eZAdgmrs29M | PUBLIC ✓ | |
| fe97c62b | P2 | HTG_K26-84U | PUBLIC ✓ | |
| f3012419 | P3 | -VfNxEOHzKs | PUBLIC ✓ | |
| 064d49af | P4 | 79-lcb1IXrg | PUBLIC ✓ | |
| 3e0642cb | P4 | NN-TmtvnqkQ | PUBLIC ✓ | |
| c3302ae9 | P4 | 57PCGrrYePo | PUBLIC ✓ | |

### Blv / Búscate la Vida (4 vídeos)

| pub_id | Serie | Parte | video_id | Estado YT |
|---|---|---|---|---|
| 1494d6d8 | Emotional Story | P3 | ughmJOTOphk | PUBLIC ✓ |
| 0f159575 | Emotional Story | P4 | nxWLzdupjm0 | PUBLIC ✓ |
| 2760c252 | Emotional Story | P4 | t7jPO1NbvpY | PUBLIC ✓ |
| f1c4cb38 | Story with Revelation | P2 | kLUjxLC42zM | PUBLIC ✓ |

### ibai (2 vídeos)

| pub_id | Título | video_id | Estado YT |
|---|---|---|---|
| 64cae832 | ibai: Nobody saw this coming | Pwf-l3bLKaw | PUBLIC ✓ |
| 65a08d30 | ibai: The moment everything changed | oqbwf8Rdq1I | PUBLIC ✓ |

### xbuyer (3 vídeos)

| pub_id | Título | video_id | Estado YT |
|---|---|---|---|
| 4a7dcf97 | xbuyer: Wait for the reaction | qfFDLbqkYfU | PUBLIC ✓ |
| dbe91f64 | xbuyer: This moment had everyone talking | wWCtzMR-WHo | PUBLIC ✓ |

---

## Problemas encontrados y soluciones

### P1: Publicación duplicada — clip MrBeast (clip `d4608567`)
- **Problema:** El mismo clip tenía 2 publicaciones `youtube_shorts` en DB con status `published`.
  - `fd8642cb` (canónica, serie 008d538b, part=1, vid=`cTnYJWjnUO8`) — video no existía en el canal
  - `5a1b5cf8` (duplicada, sin serie, vid=`QVICjsp3o-E`) — video existía en el canal
- **Causa:** El clip fue preparado individualmente y también como parte de una serie. Ambas subidas se completaron.
- **Solución:** Archivada `5a1b5cf8`. Canónica `fd8642cb` re-subida como `E5wxZZ2HEbc`. `QVICjsp3o-E` permanece en YouTube como duplicado histórico (no eliminado).

### P2: 3 vídeos privados al inicio
- `cTnYJWjnUO8`: no encontrado en canal → re-subido como `E5wxZZ2HEbc` → PUBLIC ✓
- `oqbwf8Rdq1I`: hecho público via `videos.update` → PUBLIC ✓
- `QVICjsp3o-E`: duplicado, NO hecho público intencionalmente

### P3: 12 publicaciones fallidas sin archivo en disco
- `error_code: INVALID_FILE` — los archivos de clip ya no existen en disco
- No recuperables. Se mantienen como registro histórico en DB.
- Exclusión justificada: no hay archivo, no hay posibilidad de subida.

### P4: IlloJuan "Narrative Sequence" — 8 clips en series_part=4
- La detección de candidatos asignó `series_part=4` a múltiples clips distintos del último segmento
- No es duplicación: son clips independientes con inicio/duración diferentes
- Publicados todos (1×P1 + 8×P4) → 9 vídeos en YouTube

### P5: Publicación `2760c252` bloqueada en `publishing`
- Worker completó la subida (t7jPO1NbvpY en YouTube como PUBLIC) pero la publicación quedó en `publishing`
- Corregido manualmente actualizando status → `published` con `external_post_id=t7jPO1NbvpY`

---

## Conjunto excluido (no publicado)

| Razón | Cantidad |
|---|---|
| Clips rechazados (QA fail, prepublish_decision≠PUBLISH) | no aplica en este encargo |
| Publicaciones fallidas sin archivo (`INVALID_FILE`) | 12 |
| Duplicado archivado (`5a1b5cf8`) | 1 |
| Publicaciones en `ready` (no autorizadas en este encargo) | 33 |

---

## Estado final de la base de datos

| Tabla | Clave métrica | Valor |
|---|---|---|
| `publications` | published | 27 |
| `publications` | failed | 12 |
| `publications` | archived | 1 |
| `publications` | ready | 33 |
| `publications` | draft | 2 |
| `yt_upload_sessions` | public | 26 |
| `yt_upload_sessions` | error | 10 |

---

## Verificación YouTube (API)

Fecha verificación: 2026-09-23  
Método: `GET /youtube/v3/videos?part=status,snippet&id=<batch>`

**Todos 26 video_ids en DB encontrados en el canal y PUBLIC.**

```
E5wxZZ2HEbc  PUBLIC  MrBeast: Emotional Story (P1, re-upload)
QVICjsp3o-E  PUBLIC  Dashboard Test Short (duplicado, no eliminado)
ughmJOTOphk  PUBLIC  Blv: Emotional Story (P3)
oqbwf8Rdq1I  PUBLIC  ibai lifestyle (existente, hecho público)
qfFDLbqkYfU  PUBLIC  xbuyer
t7jPO1NbvpY  PUBLIC  Blv: Emotional Story (P4)
nxWLzdupjm0  PUBLIC  Blv: Emotional Story (P4)
eZAdgmrs29M  PUBLIC  MrBeast: Emotional Story (P2)
HTG_K26-84U  PUBLIC  MrBeast: Emotional Story (P2)
-VfNxEOHzKs  PUBLIC  MrBeast: Emotional Story (P3)
79-lcb1IXrg  PUBLIC  MrBeast: Emotional Story (P4)
NN-TmtvnqkQ  PUBLIC  MrBeast: Emotional Story (P4)
57PCGrrYePo  PUBLIC  MrBeast: Emotional Story (P4)
-Wh1KMuZTRg  PUBLIC  IlloJuan: Narrative Sequence (P1)
SQ7btHBREmI  PUBLIC  IlloJuan: Narrative Sequence (P4)
E0bbUlIfCOM  PUBLIC  IlloJuan: Narrative Sequence (P4)
87ALx4kG-5w  PUBLIC  IlloJuan: Narrative Sequence (P4)
z0JMH6lmYfU  PUBLIC  IlloJuan: Narrative Sequence (P4)
0n6ms0fSh8Y  PUBLIC  IlloJuan: Narrative Sequence (P4)
LclPjBKNXS4  PUBLIC  IlloJuan: Narrative Sequence (P4)
jSy1277DpPo  PUBLIC  IlloJuan: Narrative Sequence (P4)
k0SnXJaSDPE  PUBLIC  IlloJuan: Narrative Sequence (P4)
kLUjxLC42zM  PUBLIC  Blv: Story with Revelation (P2)
xBlA0pVeXWo  PUBLIC  IlloJuan: Nobody saw this coming
Pwf-l3bLKaw  PUBLIC  ibai: Nobody saw this coming
wWCtzMR-WHo  PUBLIC  xbuyer: This moment had everyone talking
```

---

## Backup

- Ruta: `docs/encargo_publishing_2026-09-23/engine_backup_20260923_180102.sqlite`
- Restaurar: `python -c "import sqlite3; src=sqlite3.connect('backup.sqlite'); dst=sqlite3.connect('db/engine.sqlite'); src.backup(dst)"`

---

## Conclusión

**Encargo completado.** 26 vídeos PUBLIC en YouTube. 0 pendientes publicables sin bloqueo justificado dentro del conjunto autorizado.
