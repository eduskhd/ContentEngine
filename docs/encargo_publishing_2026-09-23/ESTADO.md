# ESTADO — Encargo Publishing 2026-09-23

## Objetivo
Reparar Publishing + Library, eliminar duplicados, verificar Content Engine y publicar vídeos pendientes.

## Fase actual: COMPLETADO ✓

---

## Inventario inicial (antes de cambios)

| Entidad | Cantidad |
|---|---|
| Clips totales (PUBLISH) | 22 |
| Clips en REVIEW | 58 |
| Clips con archivos en disco | 80 |
| Publicaciones youtube_shorts | 45 |
| Publicaciones con video_id (subidas) | 13 |
| Públicas en YouTube | 10 |
| Privadas en YouTube | 3 |
| Listas para subir (ready + archivo) | 13 |
| Fallidas (INVALID_FILE, sin archivo) | 12 |
| Duplicados pub (mismo clip+plataforma) | 1 |

## Vídeos en YouTube al inicio

| video_id | creator | series | part | estado |
|---|---|---|---|---|
| ughmJOTOphk | Blv | 7127f7a7 Emotional Story | 3 | PUBLIC |
| t7jPO1NbvpY | Blv | 7127f7a7 Emotional Story | 4 | PUBLIC |
| nxWLzdupjm0 | Blv | 7127f7a7 Emotional Story | 4 | PUBLIC |
| QVICjsp3o-E | MrBeast | ninguna (duplicado) | 0 | PRIVATE |
| cTnYJWjnUO8 | MrBeast | 008d538b Emotional Story | 1 | PRIVATE |
| eZAdgmrs29M | MrBeast | 008d538b Emotional Story | 2 | PUBLIC |
| HTG_K26-84U | MrBeast | 008d538b Emotional Story | 2 | PUBLIC |
| -VfNxEOHzKs | MrBeast | 008d538b Emotional Story | 3 | PUBLIC |
| 79-lcb1IXrg | MrBeast | 008d538b Emotional Story | 4 | PUBLIC |
| NN-TmtvnqkQ | MrBeast | 008d538b Emotional Story | 4 | PUBLIC |
| 57PCGrrYePo | MrBeast | 008d538b Emotional Story | 4 | PUBLIC |
| oqbwf8Rdq1I | ibai | ninguna | 0 | PRIVATE |
| qfFDLbqkYfU | xbuyer | ninguna | 0 | PUBLIC |

## Problemas identificados

### P1: Publicación duplicada — clip d4608567 (MrBeast)
- pub `fd8642cb`: canónica (series 008d538b, part=1, vid=cTnYJWjnUO8) — CONSERVAR
- pub `5a1b5cf8`: duplicada (sin serie, part=0, vid=QVICjsp3o-E) — MARCAR ARCHIVED
- En YouTube hay 2 vídeos del mismo clip. El QVICjsp3o-E es el duplicado.
- Acción: archivar `5a1b5cf8`, notar QVICjsp3o-E como duplicado en YouTube (no borrar desde aquí).

### P2: 3 vídeos en YouTube como PRIVADOS
- cTnYJWjnUO8 (MrBeast serie parte 1) — hacer público vía videos.update
- oqbwf8Rdq1I (ibai standalone) — hacer público vía videos.update
- QVICjsp3o-E (duplicado de MrBeast) — NO hacer público (es duplicado)

### P3: 12 publicaciones fallidas sin archivo
- error_code=INVALID_FILE para todos
- Los archivos nunca existieron o fueron eliminados
- No se pueden recuperar. Se dejan en `failed` como registro histórico.
- Acción: documentar, no reintentar.

### P4: IlloJuan "Narrative Sequence" — 8 clips en series_part=4
- La detección asignó part=4 a múltiples candidatos en el último segmento
- No es un error de duplicación: son clips diferentes del mismo segmento
- Para publicación: se ordenan por start_s dentro del mismo part
- Acción: publicar los 9 clips del paquete (1 en part=1, 8 en part=4)

### P5: MrBeast "Emotional Story" — clips en part=2 y part=4 duplicados
- Series 008d538b tiene 2 clips en part=2 y 3 en part=4
- Son clips diferentes del mismo segmento (no duplicados de contenido)
- Ya están todos subidos a YouTube (7/7 done)

## Pendientes para publicar (13 clips autorizados)

### Paquete: IlloJuan "Narrative Sequence" (f5b1ec7f) — 9 clips
1. pub=5dc85a4e part=1
2. pub=9faecc90 part=4
3. pub=54f78e0e part=4
4. pub=0d164bce part=4
5. pub=e89c52d1 part=4
6. pub=05aa8917 part=4
7. pub=86d49135 part=4
8. pub=4f349e46 part=4
9. pub=a0d17179 part=4

### Paquete: Blv "Story with Revelation" (48921978) — 1 clip (parte 2 solamente)
- pub=f1c4cb38 part=2 — solo hay 1 de las 4 partes renderizadas como pub

### Standalone: ibai, IlloJuan standalone, xbuyer
- pub=64cae832 (ibai)
- pub=29229884 (IlloJuan standalone)
- pub=dbe91f64 (xbuyer)

## Decisiones tomadas

- Backup SQLite WAL: docs/encargo_publishing_2026-09-23/engine_backup_20260923_180102.sqlite
- Restaurar con: python -c "import sqlite3; src=sqlite3.connect('backup.sqlite'); dst=sqlite3.connect('db/engine.sqlite'); src.backup(dst)"
- No se eliminan archivos en disco
- No se eliminan vídeos de YouTube
- Las publicaciones fallidas sin archivo se dejan como registro histórico

## Historial de fases

| Fase | Estado | Notas |
|---|---|---|
| 0. Backup + inventario | COMPLETADO ✓ | |
| 1. Corrección duplicado pub | COMPLETADO ✓ | 5a1b5cf8 archivado |
| 2. Make public 2 vídeos privados | COMPLETADO ✓ | oqbwf8Rdq1I hecho público; cTnYJWjnUO8 re-subido |
| 3. Publicar 13 clips pendientes | COMPLETADO ✓ | 13/13 PUBLIC en YouTube |
| 4. QA y verificación final | COMPLETADO ✓ | 26/26 vídeos PUBLIC verificados con API |

## Resultado final
26 vídeos en YouTube, todos PUBLIC. Ver INFORME_FINAL.md.
