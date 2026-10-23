# Concat Integration — Claude Session Checkpoint

**Last updated:** 2026-10-23  
**Session context file:** `.claude/projects/C--Users-edupo-Desktop-ContentEngine/memory/concat_integration.md`

---

## Objetivo general

Integrar Concat v0.2.8 como motor de render experimental secundario, conservando FFmpeg como predeterminado. Clips Concat almacenados en `clip_variants` sin sobrescribir originales.

---

## Estado por fase

| Fase | Estado | Notas |
|------|--------|-------|
| 1 — Investigar Concat API | COMPLETADO Y VERIFICADO | API = JSON-RPC 2.0 stdin/stdout; `concat-cli api` |
| 2 — Compilar concat-cli | COMPLETADO Y VERIFICADO | debug build en `concat-src/src/target/debug/concat-cli.exe` (67 MB) |
| 3 — Adaptador Python | COMPLETADO Y VERIFICADO | `integrations/concat/adapter.py` + `api_client.py` |
| 4 — Config + wiring | COMPLETADO Y VERIFICADO | `concat_enabled=True`, exe_path, param names corregidos |
| 5 — Library indicators | COMPLETADO Y VERIFICADO | `_engineBadge()`, badge en 3 tipos de cards, modal engine badge + variant bar |
| 6 — Experimento 12 clips | COMPLETADO Y VERIFICADO | 12/12 OK, 69–260s/clip, resultados en `clip_variants` DB |
| 7 — EditPlan dataclass | COMPLETADO Y VERIFICADO | `integrations/concat/edit_plan.py`, serialize/deserialize, to_concat_request() |
| 8 — Comparador view | COMPLETADO Y VERIFICADO | Compare tab: 2-col layout, sync playback, size stats — tested in browser |
| 9 — Publishing audit | COMPLETADO Y VERIFICADO | `clip_variants` no tiene `prepublish_decision`; endpoints publican solo desde `clips` |
| 10 — E2E tests | COMPLETADO Y VERIFICADO | 13 PASS, 0 FAIL, 1 WARN — `_e2e_concat_test.py` |
| 11 — Drive sync | COMPLETADO Y VERIFICADO | 14 archivos subidos a Drive; previous archived |
| Release build | BLOQUEADO | SAC (Smart App Control) bloquea nuevos compilados. Debug OK para testing. |

---

## Instalación realizada

- **concat-cli v0.2.8** compilado en `C:\Users\edupo\Desktop\concat-src\src\target\debug\concat-cli.exe`
- **Build deps:** MSVC Build Tools, LLVM 23.1.4, FFmpeg 9.0.2 dev en `C:\Users\edupo\Desktop\ffmpeg-dev\`
- **Runtime PATH:** `C:\Users\edupo\Desktop\ffmpeg-dev\bin` + `C:\Program Files\LLVM\bin` (via `_build_env()`)
- **Release build BLOQUEADO** por Smart App Control — no es bloqueante para testing

---

## Archivos creados / modificados

### Nuevos
- `integrations/concat/api_client.py` — JSON-RPC client sobre subprocess stdin
- `integrations/concat/edit_plan.py` — EditPlan dataclass + Concat translator (Phase 7)
- `experiments/concat_experiment_phase6.py` — Script experimento 12 clips
- `_fix_variant_sizes.py` — Script one-shot: rellena `file_size_bytes` desde disco

### Modificados
- `integrations/concat/adapter.py` — reescrito MCP→JSON-RPC, dos fases, fps int fix
- `integrations/concat/__init__.py` — param names: mcp_timeout_s→api_timeout_s
- `engine/config.py` — concat_enabled=True, exe_path actualizado a concat-cli
- `engine/database.py` — `get_clip_variant()`, `render_engine` en `_CLIP_COLS`
- `api/main.py` — `/clip-variants/{id}/video`, `/clips/{id}/render-concat`, `/clips/{id}/variants`
- `dashboard/index.html` — `_engineBadge()`, badges en cards, modal engine badge, variant bar, Concat button, Compare tab con sync fix

---

## Pruebas ejecutadas y resultados

| Prueba | Resultado |
|--------|-----------|
| `concat-cli --version` | `concat-cli 0.2.8` OK |
| `concat_available()` | `True` OK |
| Smoke test (15s 9:16 clip, start=0) | OK, 74s, 8.3 MB |
| Proxy test (360p, start=10) | TIMEOUT (debug build lento con upscale) |
| Experimento Phase 6 (12 clips) | **12/12 OK** — gaming 4/4, reactions 4/4, dynamic 4/4 |
| FFmpeg pipeline sin cambios | OK (concat_enabled no altera ruta FFmpeg) |
| Compare tab — layout 2 columnas | OK (browser verified) |
| Compare tab — video load FFmpeg | OK (readyState=4, src=/clips/{id}/preview) |
| Compare tab — video load Concat | OK (readyState=4, src=/clip-variants/{id}/video) |
| Compare tab — sync playback | OK (delta 0.01s después de fix cmpSync) |
| Compare tab — stats size | OK (FFmpeg 20054KB, Concat 9169KB) |
| Publishing audit | SAFE — clip_variants sin prepublish_decision |

---

## Errores resueltos en esta sesión

| Error | Causa | Fix |
|-------|-------|-----|
| `is_available()` → False | `--version` sin `_build_env()` | Añadido `env=_build_env()` |
| Phase 2 timeout (120s) | Usaba api_timeout en vez de export_timeout | Dos clientes separados |
| `invalid type: floating point X, expected i64` | `fps` float del DB pasado como `rateNum` | `int(req.fps)` en project.create + export.run |
| UnicodeEncodeError en script | Caracteres Unicode en terminal cp1252 | Reemplazados por ASCII |
| `cmpSync` no disparaba play inicial | Guard `< 0.2s` impide play cuando ambos en t=0 | Añadido `!target.paused &&` antes del guard |
| Botones "CONCAT ?" sin tamaño | `file_size_bytes=0` en DB | `_fix_variant_sizes.py` → 12/12 rows corregidos |
| `/clip-variants/{id}/video` → 404 | Servidor antiguo sin nuevo código | Restart servidor |

---

## Estado de DB

- `clip_variants`: 25 filas total; 12 con `render_status=DONE` y `file_size_bytes` corregidos; 13 con `path missing` (runs anteriores con paths stale)
- `clips.render_engine` columna existe, permite `update_clip(id, render_engine='concat')`
- No se han ejecutado migraciones destructivas. Sin cambios en jobs históricos.

---

## Próximo paso: Phase 10 — E2E tests

Ejecutar el checklist de 20 items en `audits/concat_integration/E2E_TEST_RESULTS.md`.

### Categorías:
1. Disponibilidad del adaptador
2. Pipeline FFmpeg intacto (no regresión)
3. Render de variant vía endpoint /render-concat
4. Compare tab UI (verificado en browser)
5. Publishing safety
6. DB integridad

---

## Decisiones que requieren autorización

1. **Release build de concat-cli**: Para rendimiento en producción (5x más rápido), el usuario debe deshabilitar Smart App Control temporalmente y ejecutar `cargo build --release -p concat-cli` desde `C:\Users\edupo\Desktop\concat-src\src\`.

2. **Google Drive sync (Phase 11)**: Requiere `gcloud auth login` o token OAuth. Usuario debe ejecutar `! python tools/drive_sync.py` con credenciales activas.

3. **concat_enabled en producción**: Actualmente `True` para testing. Si se despliega a usuarios, volver a `False` hasta que el release binary esté disponible.
