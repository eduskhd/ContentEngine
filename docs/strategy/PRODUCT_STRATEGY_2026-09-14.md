# ContentEngine — Estrategia de Producto
**Fecha:** 2026-09-14  
**Autor:** Análisis estratégico asistido por IA  
**Versión:** 1.0

---

## ÍNDICE

1. Estado actual del producto
2. Mapa del mercado actual
3. Matriz competitiva
4. Protocolo de benchmarks comparativos
5. Oportunidades de negocio identificadas
6. Viabilidad económica
7. Viabilidad técnica
8. Riesgos y dependencias críticas
9. Las cinco preguntas estratégicas clave

---

## 1. Estado actual del producto — Inventario de capacidades

### 1.1 Qué hace ContentEngine hoy

ContentEngine es una herramienta privada de uso local que convierte vídeos de formato largo en clips verticales (9:16) listos para redes sociales. Opera completamente offline salvo la descarga inicial del vídeo. El flujo completo tiene 12 pasos:

```
INGEST → PROXY(360p/2fps) → TRANSCRIPCIÓN → DETECCIÓN DE CANDIDATOS →
ANÁLISIS VISUAL + ANÁLISIS AUDIO (paralelo) → AJUSTE DE PLATAFORMA →
PUNTUACIÓN DE VIRALIDAD → SKILLS → RENDER → QA/GATE → CLIPS LISTOS
```

### 1.2 Capacidades técnicas diferenciales

| Capacidad | Detalle | Nivel |
|---|---|---|
| Detección de candidatos | Doble pasada: sentence-peak + sliding-window (35s, 50% solapamiento), deduplicación IoU 0.5, diversidad de tipos | Alto |
| Transcripción | faster-whisper "small", caché por ruta (runs en caliente: 0s vs 100-400s en frío) | Alto |
| Renderizado one-pass | FFmpeg único: trim + crop/scale + subtítulos ASS en una sola llamada (3-7× más rápido que multi-pass) | Alto |
| Puntuación de viralidad | 9 componentes heurísticos + blend LLM opcional (claude-haiku, 30%) | Medio-Alto |
| Captions karaoke | Formato ASS, word-level, 3 presets (impact/aura/glowing_bold), color &HAABBGGRR | Medio-Alto |
| Proxy de análisis | 360p/2fps generado una vez, reutilizado por todos los candidatos | Alto |
| Encoding hardware | Auto-detección QSV → NVENC → libx264 veryfast (lru_cached) | Alto |
| Protección SSRF | validate_url() bloquea IPs privadas y endpoints de metadatos | Alto |
| Caché de transcripción | Basada en ruta de archivo: same file → skip transcription | Alto |

### 1.3 Lo que aún no hace

- **Reencuadre inteligente:** Solo crop centrado. Sin tracking de caras.
- **Publicación social:** Adaptadores TikTok/Instagram/YouTube existen como stubs; OAuth no configurado.
- **Multi-usuario:** Base de datos global, sin workspace isolation.
- **Acceso web:** Solo localhost, sin autenticación, sin reverse proxy.
- **Traducciones / doblaje IA:** No implementado.
- **App móvil:** No existe.
- **Scheduling:** No existe.

### 1.4 Benchmarks actuales (Intel QSV, vídeo 2 min, 3 clips)

| Escenario | Tiempo total |
|---|---|
| Run en frío (descarga + transcripción) | ~360 s |
| Run en caliente (misma fuente, caché) | ~28 s |
| Solo render (re-captions) | ~21 s |

---

## 2. Mapa del mercado actual

### 2.1 Competidores analizados

Se analizaron 10 herramientas del mercado de AI clipping: OpusClip, Klap, Vizard, Munch, Submagic, Captions.ai, Descript, VEED, Riverside y CapCut.

### 2.2 Segmentos del mercado

El mercado de AI clipping se divide en tres capas con necesidades distintas:

**Capa 1 — Clip-only / Virality-first**
Herramientas que sólo recortan y reencuadran. Velocidad máxima, mínima fricción.
- *OpusClip, Klap, Munch*
- Precio: $0-29/mes; límite por créditos.

**Capa 2 — Editing-first / Control**
Plataformas que añaden edición manual sobre el clip detectado. Mayor control, mayor curva de aprendizaje.
- *Vizard, Descript, Submagic*
- Precio: $12-41/mes.

**Capa 3 — Full-workflow / Recording-first**
Plataformas que graban, editan y distribuyen dentro de un mismo flujo.
- *Riverside, VEED, CapCut*
- Precio: $0-29/mes; Riverside en cabeza de mercado para podcasters.

### 2.3 Tendencias clave detectadas

1. **Explosión de la demanda:** 60%+ de los podcasters ya usan IA para edición en 2026. Las agencias de clipping (ej. Clipping Culture) mantienen 30.000-40.000 editores. El mercado aún no está saturado en el segmento medio-profesional.

2. **Créditos como modelo dominante:** La mayoría cobra por minuto procesado. Creadores prolíficos (>10h/mes) pagan $50-200/mes o más. Esta fricción es una oportunidad real.

3. **Idiomas como barrera de entrada:** OpusClip cubre 25+ idiomas; Klap cubre 52 (captions) y 29 (doblaje). El mercado en español, portugués y otros idiomas no-ingleses está infra-servido.

4. **Privacidad y soberanía de datos:** Ningún competidor principal ofrece procesamiento 100% local. Los creadores con contenido sensible (negocios, clínicas, despachos) no tienen alternativa.

5. **Agencias como cliente no atendido:** Las herramientas actuales están diseñadas para el creador individual. No hay herramientas de batch, gestión de clientes, o flujos de aprobación para agencias de contenido.

---

## 3. Matriz competitiva

| Capacidad | ContentEngine | OpusClip | Klap | Vizard | Descript | Riverside | CapCut |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Procesamiento local / offline | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Sin límite de créditos / minutos | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ |
| Privacidad total (datos no salen) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Detección dual-pass con IoU | ✅ | ? | ? | ❌ | ❌ | ❌ | ❌ |
| Captions karaoke word-level | ✅ | ✅ | ✅ | ⚠️ | ✅ | ⚠️ | ✅ |
| Renderizado 1-pass (velocidad) | ✅ | ? | ? | ? | ? | ? | ? |
| Face tracking / reencuadre IA | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Publicación social directa | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Multi-usuario / workspace | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Soporte >25 idiomas | ⚠️* | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| Acceso desde navegador/móvil | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Precio por crédito / mes | $0** | $15-29 | ?/mes | $12+ | $16+ | $24+ | $0-? |

*faster-whisper soporta múltiples idiomas por defecto  
**herramienta interna, sin monetización activa

### 3.1 Ventajas competitivas reales de ContentEngine

1. **Procesamiento local sin límites:** Procesa 100h de vídeo sin coste variable. Ningún competidor lo ofrece.
2. **Privacidad por diseño:** Los datos nunca salen del ordenador. Único en el mercado.
3. **Velocidad de render:** 1-pass FFmpeg vs multi-pass de la competencia.
4. **Coste de operación cercano a cero:** Solo tiempo de CPU/GPU.

### 3.2 Brechas críticas frente a competidores

1. **Face tracking:** Todos los líderes lo tienen. ContentEngine usa crop centrado.
2. **Acceso web / móvil:** Imposible usar desde dispositivo remoto o en equipo.
3. **Publicación social:** Stubs no operativos.
4. **Multi-usuario:** Única persona puede usarlo.

---

## 4. Protocolo de benchmarks comparativos

Para validar objetivamente la posición competitiva, se propone el siguiente protocolo de pruebas comparativas:

### 4.1 Conjunto de prueba

- **3 vídeos de referencia:**
  - V1: Podcast 60 min, inglés, entrevista, múltiples speakers
  - V2: YouTube 30 min, español, tutorial, una voz
  - V3: Conferencia 45 min, inglés, slides + presenter cam

### 4.2 Métricas a medir

| Métrica | Método |
|---|---|
| Tiempo total de procesamiento | Cronómetro manual, desde submit hasta clip descargable |
| Número de clips detectados | Conteo en output |
| Calidad de detección (subjetivo) | Escala 1-5 por evaluador humano: ¿el clip tiene inicio/final natural? |
| Calidad de captions | Escala 1-5: sincronía, legibilidad, precisión |
| Calidad de reencuadre | Escala 1-5: ¿el sujeto está centrado? |
| Coste por hora de vídeo procesado | Calculado sobre plan de suscripción usado |
| Clip más viral (si herramienta lo indica) | Comparación de clip top 1 entre herramientas |

### 4.3 Herramientas a comparar

ContentEngine vs OpusClip (Pro) vs Klap (Pro) vs Riverside (Pro)

### 4.4 Herramienta de evaluación

Spreadsheet con puntuaciones ciegas (el evaluador no sabe qué herramienta generó cada clip). Dos evaluadores independientes. Media ponderada.

---

## 5. Oportunidades de negocio identificadas

### 5.1 Oportunidad A — SaaS auto-hospedado para agencias de contenido

**Hipótesis:** Las agencias de clipping (decenas de miles de editores humanos) necesitan herramienta de batch con gestión de clientes. Las herramientas actuales están diseñadas para creadores individuales, no para flujos de producción en volumen.

**Modelo:** ContentEngine empaquetado como servidor local (o VPS propio), multi-workspace, panel de gestión de clientes, facturación por volumen de vídeo procesado. Sin límites de créditos.

**Tamaño de mercado (estimado):** Si sólo el 1% de los 30.000-40.000 editores de agencias paga $50/mes → $180k-$240k MRR.

**Barrera de entrada que usamos:** Local/privado + batch sin límites = diferenciación real.

### 5.2 Oportunidad B — Herramienta B2B para sectores con privacidad exigente

**Hipótesis:** Clínicas, despachos de abogados, consultoras y empresas B2B producen contenido de vídeo con datos sensibles. No pueden usar herramientas cloud sin comprometer privacidad. No tienen alternativa actual.

**Modelo:** ContentEngine como appliance de escritorio o servidor interno. Venta de licencia perpetua o suscripción anual por empresa. Sin procesamiento cloud.

**Ventaja única:** Ningún competidor puede ofrecer esto. No es una feature que se pueda copiar fácilmente (es una arquitectura diferente).

### 5.3 Oportunidad C — Mercado hispanohablante infra-servido

**Hipótesis:** La mayoría de herramientas están optimizadas para inglés. La detección de momentos virales, los prompts LLM internos, y la UX están en inglés. Los creadores hispanohablantes tienen peores resultados.

**Modelo:** ContentEngine como la primera herramienta de clipping IA nativa en español. Modelos de transcripción ya lo soportan; habría que adaptar la virality scoring y el LLM prompt.

**Ventaja:** Primer mover en un mercado de 500M+ hablantes.

### 5.4 Oportunidad D — Tier de agencia sobre modelo SaaS cloud

**Hipótesis:** Si se resuelve face-tracking y publicación social, ContentEngine podría competir en el mercado cloud contra OpusClip en el segmento de poder (agencias, studios, marcas).

**Riesgo:** Alta inversión, competencia directa con empresas capitalizadas. No recomendado como primera jugada.

---

## 6. Viabilidad económica

### 6.1 Estructura de costes actuales

| Componente | Coste variable por clip | Notas |
|---|---|---|
| Transcripción (faster-whisper local) | ~$0 | CPU/GPU propio |
| LLM virality boost (claude-haiku) | ~$0.001-0.003 | Solo si ANTHROPIC_API_KEY activo; opcional |
| FFmpeg render | ~$0 | CPU/GPU propio |
| Almacenamiento | ~$0.02-0.05/GB | Disco local o NAS |

**Coste marginal por hora de vídeo procesado ≈ $0.05-0.15** (solo LLM + storage).

Comparado con OpusClip Pro ($29/mo, 300 créditos = 300 min) → **$0.097/min procesado**. ContentEngine puede procesar en caliente por **$0.001-0.005/min**.

### 6.2 Modelos de monetización viables

**Modelo 1 — Licencia de escritorio (B2B privacidad)**
- Precio: $299-499 licencia anual por puesto
- Costes: soporte, distribución, actualizaciones
- Break-even: ~50 clientes

**Modelo 2 — SaaS auto-hospedado (agencias)**
- Precio: $99-299/mes por workspace (ilimitado)
- Costes: infraestructura mínima (solo dashboard web + auth), soporte
- Ventaja: margen bruto >85%

**Modelo 3 — Open source + plan empresarial**
- Core open source → traction de comunidad
- Plan empresarial: multi-usuario, SSO, soporte, white-label
- Riesgo: requiere comunidad activa para funcionar

### 6.3 Inversión estimada para llegar a v1.0 comercial

| Ítem | Estimación |
|---|---|
| Face tracking (MediaPipe o similar) | 2-3 semanas dev |
| Auth multi-usuario básica (API key por workspace) | 1 semana |
| Publicación social (YouTube + TikTok OAuth funcional) | 2-3 semanas |
| Onboarding / instalador | 1 semana |
| Landing page + docs | 1 semana |
| **Total estimado** | **7-11 semanas** |

Con un solo desarrollador a tiempo completo, se puede lanzar una versión comercial mínima en **2-3 meses**.

---

## 7. Viabilidad técnica

### 7.1 Lo que ya está construido y funciona

La infraestructura más difícil ya existe:
- Pipeline end-to-end probado
- Transcripción + caché rápida
- Renderizado 1-pass hardware-accelerated
- ASS karaoke captions con editor en dashboard
- Detección de candidatos dual-pass
- SQLite WAL robusto con cleanup de zombies

### 7.2 Las tres brechas técnicas críticas

**Brecha 1 — Face tracking para reencuadre**
- Solución: MediaPipe Face Detection (Google, open source, local, CPU)
- Alternativa: YOLOv8-face (más preciso, requiere modelo ~6MB)
- Integración: modificar `engine/renderers/render_clip.py` para calcular x_offset dinámico por frame
- Complejidad: media (3-5 días para MVP, 2-3 semanas para producción robusta)
- Riesgo: latencia añadida en renders. Mitigación: calcular posición media por segmento (no frame a frame)

**Brecha 2 — Autenticación y multi-workspace**
- Solución: API key por workspace en header `X-API-Key`, middleware en FastAPI
- DB: añadir `workspace_id` a `creators`, `videos`, `jobs`, `clips`
- Complejidad: media (1-2 semanas incluyendo migración DB)
- Riesgo: migración de datos existentes. Mitigación: workspace_id=0 para datos históricos

**Brecha 3 — Publicación social funcional**
- Los stubs TikTok/Instagram/YouTube ya existen
- YouTube Data API v3 es la más documentada y estable
- TikTok Content Posting API tiene restricciones de acceso (requiere solicitud de acceso oficial)
- Instagram Graph API requiere cuenta Business y aprobación Meta
- Complejidad: media-alta (2-3 semanas por plataforma, empezar con YouTube)
- Riesgo: cambios de API externos. Mitigación: diseñar con adaptador intercambiable (ya está hecho)

### 7.3 Dependencias técnicas a monitorizar

| Dependencia | Riesgo | Mitigación |
|---|---|---|
| faster-whisper / CTranslate2 | Bajo (open source activo) | Pin versión en requirements.txt |
| FFmpeg | Muy bajo (estándar de facto) | Bundlear binario en distribución |
| anthropic SDK (LLM optional) | Bajo (API estable) | Ya es opcional; heurístico funciona solo |
| yt-dlp | Medio (rompe con cambios de YouTube) | Actualizar yt-dlp frecuentemente |
| SQLite | Muy bajo (parte de Python stdlib) | Sin riesgo |

---

## 8. Riesgos y dependencias críticas

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Face tracking añade latencia inaceptable | Media | Alto | Calcular por segmento, no por frame |
| YouTube/TikTok APIs cambian términos | Alta | Medio | Publicación como feature secundaria, no bloqueante |
| Competidor copia posicionamiento local/privado | Media | Alto | Velocidad de ejecución + comunidad |
| SQLite no escala con múltiples usuarios concurrentes | Alta (>10 usuarios) | Alto | Migrar a PostgreSQL en ese momento |
| Dependencia de ANTHROPIC_API_KEY para scoring óptimo | Baja | Bajo | Heurístico sigue funcionando sin LLM |
| Instalación compleja frena adopción | Alta | Alto | Crear instalador Windows/Mac con dependencias bundleadas |

---

## 9. Las cinco preguntas estratégicas clave

### ¿Para quién debemos construir?

**Para agencias de contenido y creadores prolíficos que producen más de 10 horas de vídeo al mes.** No para el creador casual que sube un vídeo semanal (ese mercado ya lo tiene OpusClip con su plan free). El cliente ideal es quien siente el dolor de los créditos, la latencia cloud y las restricciones de privacidad. También: empresas y profesionales con contenido sensible que no pueden usar herramientas cloud.

### ¿Qué problema resolveremos mejor que nadie?

**Procesamiento de vídeo sin límites, sin cloud y sin compromisos de privacidad.** Ningún competidor puede ofrecer "procesa lo que quieras, tus datos no salen de tu máquina, cuesta $0 variable". Esta combinación es técnicamente imposible para las herramientas cloud-first, y es exactamente lo que ContentEngine ya hace hoy.

### ¿Por qué elegirían y pagarían nuestro producto?

1. **Ahorro económico masivo:** Una agencia que procesa 50h/mes en OpusClip Pro pagaría >$500/mes en créditos. ContentEngine cuesta $0 variable.
2. **Sin fricción de privacidad:** Para sectores regulados (sanidad, legal, finanzas), es la única opción que cumple sin configuración adicional.
3. **Velocidad en caliente:** 28 segundos para un run cálido es el mejor tiempo de respuesta del mercado para procesamiento local.

### ¿Qué debemos hacer ahora?

**Tres cambios para ir al mercado en 2-3 meses:**
1. **Face tracking básico** (MediaPipe, 2-3 semanas): Cierra la brecha visual más visible frente a competidores.
2. **Auth + multi-workspace mínimo** (1-2 semanas): Permite vender licencias a equipos de 2-5 personas.
3. **Instalador con dependencias bundleadas** (1 semana): Elimina la barrera de entrada técnica.

Con esto: producto vendible, diferenciado, y listo para primeros clientes de pago.

### ¿Qué debemos dejar de hacer?

1. **Publicación social como prioridad:** Los stubs están bien donde están. No hay que activarlos ahora; son complejidad sin retorno inmediato.
2. **Competir en features de UI/UX con OpusClip:** No vamos a ganar ese juego. Nuestra ventaja es técnica y económica, no estética.
3. **Iterar sin cliente:** La siguiente iteración grande debe estar guiada por un cliente real (agencia, empresa, creador prolífico) con necesidad concreta. Sin ese feedback, optimizamos lo equivocado.

---

*Este documento es un análisis estratégico basado en el estado del código a fecha 2026-09-14 e investigación de mercado público. No expone secretos ni datos privados. No implementa cambios de producto.*
