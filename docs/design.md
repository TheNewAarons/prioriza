# Diseño del panel (`dashboard/`)

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

Dirección visual y tokens del panel Dash. Quien implemente no decide diseño: si algo no está aquí, se resuelve con los tokens existentes y la regla más cercana, y se anota en `TASK_PLAN.md`.

## 1. Para quién y para qué

- **Quién lo usa**: gestores de lista de espera de un servicio de salud, revisores que aprueban planes y personas de investigación que leen resultados. Lo usan sentados, con tiempo, en un computador de escritorio; a veces en una tablet en reunión.
- **Trabajo principal**: entender el estado de la lista y decidir, con evidencia explicada, si un plan propuesto por el sistema se aprueba. El panel apoya, no decide: cada número del sistema se muestra con su explicación y cada plan muestra que espera revisión humana.
- **Tono**: sobrio, institucional sin imitar a ninguna institución real (sin logos ni colores del Minsal, Fonasa o servicios de salud). Español de Chile, voz activa, frases cortas.

## 2. Idea visual

El material del tema es **el tiempo de espera** y el **pabellón**. Dos decisiones lo traducen:

1. **Verde quirófano como color de marca.** El verde-azulado de la ropa de pabellón (`scrub`) es reconocible para cualquiera que trabaje en un hospital y no es el azul corporativo ni el verde ácido de los paneles genéricos. Se usa en navegación, acciones primarias y foco; nunca para estados (los estados tienen su propia familia).
2. **La regla de espera** es el elemento memorable, y el único gesto audaz del panel: una franja horizontal de 0 a 730 días, como la regla graduada de un pasillo, donde se marcan la mediana y el p90 de espera de la lista y, debajo, la distribución de plazos GES (en riesgo y vencidas). Aparece arriba en el resumen y, en miniatura, en el detalle de un paciente (dónde cae su espera en la regla). Todo lo demás es silencioso: tablas limpias, cifras tabulares, mucho aire.

Descartado a propósito: fondo crema con acento terracota, fondo negro con acento ácido, maquetación de diario con filetes, el kit de tarjetas redondeadas idénticas con sombra gris, etiquetas en mayúsculas sobre cada título, tipografía monoespaciada para datos, flechas `→` en botones.

## 3. Tokens

Se definen una vez en `dashboard/src/dashboard/assets/tokens.css` (variables CSS) y en `dashboard/src/dashboard/theme.py` (las mismas cifras en Python, para Plotly). Nunca se escribe un color o una medida suelta fuera de esos dos archivos.

### Color

| Token | Hex | Uso | Contraste |
|---|---|---|---|
| `--paper` | `#F6F8F7` | Fondo de la página (gris verdoso muy claro, no crema) | — |
| `--surface` | `#FFFFFF` | Tablas, paneles de detalle, formularios | — |
| `--zone` | `#E9EFED` | Zonas de filtros y la barra lateral | — |
| `--ink` | `#1C2B2E` | Texto principal (pizarra azulada, no negro teñido) | 14,6:1 sobre `--surface` |
| `--ink-muted` | `#4B5B5F` | Texto secundario, ejes | 7,1:1 sobre `--surface` |
| `--rule` | `#C9D3D1` | Filetes de tabla y separadores | decorativo |
| `--scrub` | `#17655F` | Marca: navegación activa, botón primario, enlaces | 6,9:1 con texto blanco |
| `--scrub-deep` | `#0E4743` | Hover del primario y anillo de foco | 10,4:1 sobre `--surface` |
| `--scrub-tint` | `#D7EAE7` | Fondo de la fila o ítem seleccionado | — |

Estados (siempre con texto e icono, nunca solo color; texto sobre su fondo cumple AA):

| Estado | Texto | Fondo | Icono | Uso |
|---|---|---|---|---|
| `ok` | `#235C33` | `#DDEFE2` | ✓ | Plan aprobado, GES cumplida |
| `pending` | `#2D4A6B` | `#DFE8F2` | ◷ | Plan pendiente de revisión, trabajo en cola o en curso |
| `risk` | `#7A4300` | `#FBE7C6` | ▲ | GES en riesgo (vence en 30 días o menos) |
| `overdue` | `#9B2318` | `#F9DFDB` | ● | GES vencida, plan rechazado, trabajo fallido |
| `current` | `#FFFFFF` | `#17655F` | ★ | Plan vigente |

Datos (Plotly). Paleta de Okabe-Ito, segura para daltonismo, y **cada serie lleva además forma de marcador y tipo de línea propios**:

| Serie | Color | Marcador | Línea |
|---|---|---|---|
| `fifo` (orden de llegada) | `#6E6E6E` | círculo vacío | punteada |
| `priority` (solo prioridad) | `#0072B2` | cuadrado | continua |
| `optimized` (optimizada) | `#009E73` | diamante | continua |
| `optimized_overbooking` (optimizada con sobrecupo) | `#D55E00` | triángulo | guiones |

Grupos de equidad: un solo color (`--ink`) con el valor de cada grupo rotulado; la referencia (total) es una línea vertical `--ink-muted` punteada. La regla de espera usa `--ink` para la regla, `--scrub` para mediana y p90 (rotulados), y `risk`/`overdue` para las franjas GES (con rótulo y patrón de rayado en vencidas).

### Tipografía

- **Atkinson Hyperlegible Next** (Google Fonts, pesos 400, 600 y 700) para todo: títulos, texto, tablas y gráficos. Fue diseñada por el Braille Institute para distinguir caracteres parecidos (0/O, 1/l/I), algo que importa al leer códigos de entrada, días y puestos en una cola. Una sola familia; la jerarquía la dan tamaño y peso.
- Respaldo: `"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", sans-serif`.
- **Cifras**: `font-variant-numeric: tabular-nums` en tablas, indicadores y ejes (la fuente trae `tnum`); números alineados a la derecha en columnas.
- Escala (razón 1,25, base 16 px; `rem` con raíz 16 px):

| Token | Tamaño / interlineado | Peso | Uso |
|---|---|---|---|
| `--t-display` | 39 px / 1,1 | 700 | Solo la cifra principal de la regla de espera (mediana) |
| `--t-h1` | 31 px / 1,2 | 700 | Título de página (uno por página) |
| `--t-h2` | 25 px / 1,25 | 600 | Secciones |
| `--t-h3` | 20 px / 1,3 | 600 | Subsecciones, título de gráfico |
| `--t-body` | 16 px / 1,5 | 400 | Texto, celdas de tabla |
| `--t-small` | 13 px / 1,45 | 400 | Notas, rótulos de ejes, aviso |

- Títulos en tipo oración ("Lista priorizada", no "LISTA PRIORIZADA" ni "Lista Priorizada"). Sin mayúsculas sostenidas, sin cursiva para destacar una palabra, sin rótulos encima de los títulos.
- Largo de línea del texto corrido: máximo 72 caracteres (`max-width: 72ch`).

### Espaciado, forma y elevación

- Escala de 4 px: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48, `--s8` 64.
- Radios con jerarquía, no uno para todo: controles (botones, campos, insignias) `4px`; paneles y tablas `0` con filete `--rule` de 1 px; la regla de espera `0`.
- Sin sombras salvo una: el panel de confirmación de revisión (aprobar o rechazar) se eleva con `0 8px 24px rgba(28,43,46,.18)` porque es la única acción que no se deshace.
- Sin degradados ni ilustraciones decorativas.

### Movimiento

- Solo como respuesta a una acción: al aprobar o rechazar, la insignia del plan cambia con un fundido de 150 ms; al lanzar una programación, el estado del trabajo late suavemente mientras está en curso.
- `@media (prefers-reduced-motion: reduce)`: sin animaciones.

## 4. Estructura

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Aviso de investigación (franja fija, siempre visible)                     │
├────────────┬──────────────────────────────────────────────────────────────┤
│ Prioriza   │ Título de página                    revisor.local, revisor  Salir│
│            │                                                              │
│ Resumen    │ Contenido (máximo 1.280 px, alineado a la izquierda)         │
│ Lista      │                                                              │
│ Programa-  │                                                              │
│  ción      │                                                              │
│ Simulación │                                                              │
│ Equidad    │                                                              │
│            │                                                              │
│ Datos      │                                                              │
│ sintéticos │                                                              │
└────────────┴──────────────────────────────────────────────────────────────┘
```

- **Aviso permanente**: franja superior fija de 40 px, fondo `--ink`, texto blanco `--t-small` en peso 600, con el texto exacto de `shared.disclaimer.DISCLAIMER`. No se puede cerrar. Además, cada gráfico exportado y cada tabla descargable incluye el aviso como nota.
- **Barra lateral**: 232 px, fondo `--zone`, enlaces en `--ink`; el activo con barra izquierda de 4 px `--scrub` y texto `--scrub-deep` en 600 (no solo color: también la barra). Abajo, la corrida sintética en uso (id corto, tamaño, fecha de corte).
- **Cabecera de página**: título `--t-h1` y, a la derecha, el usuario y su rol en texto ("revisor.local, revisor") y el botón "Salir".
- **Contenido**: alineado a la izquierda, ancho máximo 1.280 px, márgenes `--s6`. Las secciones se separan con `--s7` de aire y un título `--t-h2`, no con tarjetas.
- **Responsivo**: bajo 992 px la barra lateral pasa a un menú desplegable arriba; bajo 576 px las tablas muestran las columnas esenciales y el resto en el detalle de la fila; los gráficos ocupan el ancho completo.

### Acceso

Una pantalla de acceso con un campo "Clave de API" y el botón "Entrar". La clave se valida contra `GET /v1/me` y se guarda solo en la sesión del navegador (`dcc.Store(storage_type="session")`). Los botones que el rol no puede usar no se muestran (no se muestran deshabilitados sin explicación); donde una acción falta por rol, una línea `--t-small` lo dice: "Solo un revisor puede aprobar o rechazar planes."

## 5. Páginas

### Resumen

Cifras del boceto ilustrativas; las reales salen de la API.

```
Resumen de la lista de espera                      Corrida d7a0c251, 100.000 entradas
─────────────────────────────────────────────────────────────────────────────
 [La regla de espera]
 0        90       180       270   ▼301 mediana        540       ▼p90 ...   730 días
 ├────────┼────────┼────────┼──────●──────────────────┼───────────●──────────┤
 GES en riesgo ▲ ████  1.234     GES vencidas ● ▒▒▒▒▒▒▒ 3.866

 Entradas en espera   Mediana de espera   p90 de espera   GES en riesgo   GES vencidas
 100.000              301 días            770 días        1.234           3.866

 Por tipo de atención                         Plan vigente
 tabla: consulta / cirugía (entradas,         ★ Plan 1a2b, aprobado por revisor.local
 mediana, p90, GES en riesgo, vencidas)       el 9 oct; 13.750 citas. Ver plan
```

- Los indicadores son cifras `--t-h2` en 700 con su rótulo `--t-small` debajo, en una fila, separadas por aire y un filete superior de 2 px en el color de su estado cuando lo tienen (riesgo, vencidas). No son tarjetas.
- "En riesgo" = GES no vencida con plazo en 30 días o menos desde la fecha de corte; "vencida" = plazo anterior a la fecha de corte. Los cortes se escriben en la nota del gráfico.

### Lista priorizada

- Zona de filtros (`--zone`): servicio de salud, especialidad, tipo de atención, prioridad clínica, GES (sí/no) y tier GES; orden por puesto, puntaje o fecha de ingreso.
- Tabla paginada en el servidor (50 filas): puesto en su cola, puntaje (con una barra horizontal fina de 0 a 100 dentro de la celda y el número al lado), prioridad clínica, días de espera, GES con insignia de estado (▲ en riesgo, ● vencida), especialidad, servicio.
- Al elegir una fila se abre el detalle a la derecha (o abajo en pantallas chicas): **desglose del puntaje** como barras horizontales por componente (prioridad clínica, espera, plazo GES…), cada una rotulada con su aporte en puntos; el tier GES y su razón; la explicación en texto de `priority.explain`; y la miniatura de la regla de espera con la espera de esa entrada marcada.
- Nota fija bajo la tabla: "La prioridad clínica la definen profesionales; el sistema no la cambia."

### Programación

Cuatro zonas en secuencia (aquí sí hay orden real, así que van numeradas 1 a 4):

1. **Pedir una programación** (solo gestor): política (orden de llegada, solo prioridad, optimizada), semanas del horizonte, sobrecupo (solo para optimizada) y límite de tiempo. Botón "Programar". Debajo, los trabajos de la sesión con su estado (◷ en cola, ◷ en curso con latido, ✓ terminado, ● falló con el mensaje).
2. **Revisar el plan**: selector de plan (los más recientes primero, con insignia de estado). Para el plan elegido:
   - Encabezado: política, horizonte, quién lo pidió y cuándo, estado de revisión, vigente o no.
   - **Calendario por recurso**: mapa de calor con recursos en filas y días del horizonte en columnas; cada celda muestra el número de citas (texto dentro de la celda) y el color solo refuerza; las celdas con sobrecupo llevan un borde y el símbolo `+n`.
   - **Garantías GES no cumplidas** con su causa, agrupadas por causa (sin bloque en el horizonte, vence antes del primer bloque, cupos tomados), con el conteo y la tabla de entradas.
   - Explicaciones por entrada, filtrables por estado.
   - **Descargar CSV**: botón `btn--quiet` bajo el encabezado del plan, visible para todos los roles; baja las citas del plan (`GET /v1/plans/{id}/export`) con el aviso de investigación en la primera línea `# aviso:`. Un mensaje `alert--error` junto al botón dice qué falló.
   - **Por qué este cupo**: las filas de las tablas de GES y de explicaciones son seleccionables (una a la vez). Al elegir una se muestra, bajo las tablas, el motivo del cupo: texto del plan, tabla Dato/Valor (estado, puntaje y puesto, prioridad clínica como dato de entrada, plazo GES, fase en que se agendó, cita, sobrecupo, riesgo de inasistencia y de desborde) y las barras de aporte de cada componente (`component_bars`, igual que en el detalle de la lista). Solo se muestra lo que entrega `GET /v1/plans/{id}/entries/{entry}/reason`; lo que falta se escribe como "No quedó agendada" o "—".
3. **Decidir** (solo revisor): botones "Aprobar plan" y "Rechazar plan" con nota opcional; abre el panel de confirmación elevado que repite el plan y su efecto ("Aprobar no lo deja vigente: un gestor debe activarlo."). Para gestor, si el plan está aprobado: "Marcar como vigente". La auditoría (quién, rol, cuándo, nota) se lista debajo.

4. **Comparar planes**: dos selectores ("Plan A" y "Plan B", con los mismos planes del selector principal; por defecto el más antiguo contra el más reciente). Muestra: insignias de estado y vigencia de cada plan, tabla Dato/Plan A/Plan B (política, revisión, vigente, quién lo pidió, cuándo, solver), una frase de lectura generada desde los datos ("el plan B es mejor en 1, peor en 2 e igual en 1"), la tabla de métricas con diferencia `B - A` y la columna "Lectura" (`✓ Mejor en B`, `● Peor en B`, `Igual`, `Solo informa`; icono y texto, nunca solo color), y la equidad por grupo en un `details` abierto con **lo desfavorable para B primero** (máximo 300 filas, con nota si hay más). Si los planes son de corridas distintas la API responde 422 y el panel muestra su mensaje. Los resultados desfavorables nunca se ocultan.

### Simulación

- Gráfico de intervalos por métrica elegida (atendidos, mediana de espera, GES incumplidas, uso de cupos, cupos perdidos, desborde): punto con barra de IC 95 % por política, con marcador y línea propios de cada política, y el valor rotulado.
- Tabla de comparaciones pareadas (diferencia, IC 95 %, réplicas en que mejora) con la dirección de la métrica escrita ("menos es mejor").
- Cobertura de oferta y limitaciones de la simulación, siempre visibles bajo los gráficos (no colapsadas).

### Equidad

- Selector de política y dimensión (edad, previsión, comuna).
- Gráfico de puntos por grupo para tasa de atención, mediana de espera, exposición al sobrecupo e inasistencia: cada grupo una fila rotulada, punto con rango mín–máx entre réplicas, línea de referencia del total. Los grupos fuera de la brecha permitida se marcan con ▲ y texto.
- Frase de lectura arriba, generada desde los datos: "La exposición al sobrecupo va de 22,7 % a 26,8 % entre grupos de edad; el grupo 0-14 es el más expuesto." Si un grupo queda peor, se dice tal cual.

## 6. Plotly

Plantilla única `prioriza` en `theme.py`: fuente Atkinson Hyperlegible Next 13 px, color `--ink-muted` en ejes y `--ink` en títulos, fondo `--surface`, grilla `--rule` solo horizontal, sin barra de herramientas salvo "descargar imagen", márgenes ajustados, leyenda arriba a la izquierda, `hovermode="closest"`. Cada figura lleva un título que dice lo que muestra y una anotación al pie con el aviso de investigación.

## 7. Accesibilidad (piso, no extra)

- Contrastes verificados (WCAG 2.1): `--ink` sobre `--surface` 14,6:1 y sobre `--paper` 13,7:1; `--ink-muted` sobre `--surface` 7,1:1 y sobre `--zone` 6,1:1; blanco sobre `--scrub` 6,9:1; textos de estado sobre su fondo entre 6,3:1 y 7,4:1; aviso blanco sobre `--ink` 14,6:1.

- Contraste AA para todo texto (los valores de la tabla de color ya cumplen); componentes no textuales 3:1.
- Ningún estado se comunica solo con color: insignias con icono y texto; series con marcador y línea; mapas con números.
- Foco visible: `outline: 3px solid var(--scrub-deep); outline-offset: 2px` en todo elemento interactivo.
- Gráficos con `aria-label` que resume la conclusión y una tabla equivalente debajo ("Ver datos").
- Formularios con `label` asociado; mensajes de error junto al campo.

## 8. Textos

- Nombrar por lo que la persona entiende: "Programar", "Aprobar plan", "Marcar como vigente", "Pendiente de revisión"; no "ejecutar job" ni "PATCH".
- Una acción mantiene su nombre en todo el flujo: el botón "Aprobar plan" produce "Plan aprobado por revisor.local".
- Errores que dicen qué pasó y qué hacer, sin disculpas: "La API no responde en http://127.0.0.1:8000. Levántala con `make api`." "Tu rol (lectura) no puede programar."
- Vacíos como invitación: "Todavía no hay planes. Pide uno en Programar." (solo gestor la ve; lectura ve "Todavía no hay planes.").
- Políticas con nombre humano: orden de llegada (`fifo`), solo prioridad (`priority`), optimizada (`optimized`), optimizada con sobrecupo (`optimized_overbooking`).
