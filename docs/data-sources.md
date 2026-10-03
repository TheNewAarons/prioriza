# Fuentes de datos

> Herramienta de investigación con datos sintéticos. No usar para decisiones clínicas ni de gestión real sin validación institucional.

## Método

Investigación realizada por data-researcher el 2026-10-02. Verificación: sesión principal, 2026-10-02. Cada URL marcada "HTTP 200" se comprobó con curl: responde y entrega el tipo de contenido esperado (PDF o página). Solo la Glosa III-2025 (E1) se descargó y se extrajo su texto con pypdf; sus cifras están verificadas en la fuente primaria. Para el resto de los PDF y XLSX, "HTTP 200" confirma que el archivo existe, no su contenido.

## Resumen de decisiones

- **E1 (Glosa 06 III-2025)** como fuente principal de calibración: proporciona tamaños y composición de listas de espera por servicio, especialidad, previsión y rangos de tiempos, junto con tasas de egreso por inasistencia.
- **E2 (Glosas IV-2025 e I-2026)** como serie de validación: amplía la visibilidad de tendencias trimestrales (pendiente extracción completa).
- **E3 (GES Superintendencia)** para composición de garantías explícitas por problema de salud, con advertencia de denominadores distintos al Minsal.
- **E4 (Literatura: Salinas 2014, Sepúlveda 2024, Dunstan 2023, Barahona 2023)** como priors parametrizados de tasas base de inasistencia, documentando limitaciones por contexto (datos históricos, especificidad hospitalaria, no equivalencia con inasistencia pura).
- **E5 (Catálogo datos.gob.cl)** para estructura de la red sintética de establecimientos.

## Fuentes de entrada

| ID | Fuente | Organismo | URL | Formato | Granularidad | Periodo | Licencia | Última actualización | Registro | Verificación | Uso en Prioriza |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | Glosa 06 III trim. 2025 | Minsal, Subsecretaría de Redes Asistenciales | [Descargar](https://www.minsal.cl/wp-content/uploads/2025/11/1764018133827_Glosa-06-LE-III-trimestre-2025.pdf) | PDF | Nacional, 29 servicios, especialidad, sexo, edad, previsión (FONASA), rangos espera | Corte 30-09-2025 | No indicada | Extracción SIGTE 14-10-2025; publicado nov-2025 | Sin registro | HTTP 200; texto extraído (55 págs.); sha256 `b4fe13ea8afffd9d47fb33ae3a2f071dc6acc13539dd5094d0f8ba29809c4d7c` | Tamaños y composición por servicio/especialidad, distribución tiempos espera, mezcla GES/no-GES, tasa egreso por inasistencia |
| E2a | Glosa 06 IV trim. 2025 | Minsal | [Descargar](https://www.minsal.cl/wp-content/uploads/2026/02/Glosa-06-LE-IV-trimestre.pdf) | PDF | — | IV-2025 | No indicada | — | — | HTTP 200 | Validar tendencia (extracción pendiente) |
| E2b | Glosa 06 I trim. 2026 | Minsal | [Descargar](https://www.minsal.cl/wp-content/uploads/2026/07/Glosa-06-letra-a-b-c-i-j-k-comun-a-la-partida-1er-trimestre-1.pdf) | PDF | — | I-2026 | No indicada | — | — | HTTP 200 | Validar tendencia (extracción pendiente) |
| E3 | Estadísticas GES | Superintendencia de Salud | [Consultar](https://www.superdesalud.gob.cl/tax-temas-de-orientacion/garantias-explicitas-en-salud-ges-1962/) | XLSX trimestral | Casos por problema de salud y aseguradora | 2021 – mar-2026 | No indicada | — | Sin registro | HTTP 200 | Composición de garantías GES por problema de salud (XLSX pendiente abrir) |
| E4a | Salinas Rebolledo EA et al. Medwave 2014;14(09):e6023 | — | [Consultar](https://www.medwave.cl/investigacion/estudios/6023.html) | Artículo peer-reviewed | 29 servicios | 2005–2010 | CC BY-NC 3.0 | — | — | HTTP 200 | Prior paramétrico: 16,5% nacional (rango regional 8,8–20,2%), variación por especialidad y mes |
| E4b | Sepúlveda Martin CA. Tesis MSP U. de Chile 2024 | — | [Consultar](https://repositorio.uchile.cl/handle/2250/203932) | Tesis (no revisada por pares) | Por servicio | 2022 | CC BY-NC-ND 3.0 | — | — | HTTP 200 | Prior paramétrico: ~15,6% (1,185 M / 7,575 M citas); desagregación por servicio (Arica 22%, Iquique 21%) |
| E4c | Dunstan J et al. Health Care Manag Sci 2023;26(2):313-329 | — | [Consultar](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257628/) | Artículo peer-reviewed | Hospital pediátrico; por especialidad | — | CC BY 4.0 | — | — | HTTP 200 | Referencia metodológica: 20,4% (rango 4,9%–30,3% por especialidad); no usado como prior (contexto pediátrico no representativo) |
| E4d | Barahona M et al. Medwave 2023;22(3):e2667 | — | [Consultar](https://www.medwave.cl/investigacion/estudios/2667.html) | Artículo peer-reviewed | Cirugía electiva | 2018–2021 | CC BY-NC 3.0 | — | — | HTTP 200 | Suspensión de cirugía: 12,9% (2018) → 6,4% (2021); ~50% por causas del paciente; no es inasistencia pura |
| E5 | Catálogo de establecimientos | Ministerio de Salud (datos.gob.cl) | [Consultar](https://datos.gob.cl/organization/ministerio_de_salud) | CSV | Establecimientos y servicios | — | Pendiente revisar | — | — | HTTP 200 | Estructura de la red sintética (servicios, establecimientos) |

### Cifras verificadas en la Glosa 06 III-2025

- **CNE**: 2.576.371 registros / 2.134.364 personas (promedio 341 días, mediana 242 días)
- **IQ**: 417.561 registros / 365.118 personas (mediana 264 días)
- **GES**: 80.022 garantías retrasadas (promedio 136 días, mediana 71 días) sobre 3,74 M garantías (97,34% cumplidas)
- **Inasistencias** ("Dos inasistencias"): 82.420 registros (78.162 CNE, 4.258 IQ) sobre 2.707.426 egresos totales
- **Suspensiones de cirugía por causa**: administrativa 37,1%, equipo quirúrgico 34,0%, paciente 16,1% ("No se presenta" está dentro de administrativa)

### Advertencias

- La clasificación de causales de suspensión cambió en 2023 (Manual REM 1.1); no es comparable con periodos previos.
- El % de cumplimiento GES de la Superintendencia usa denominador distinto al Minsal (garantías abiertas vs procesadas); no mezclar.
- Dunstan et al. (E4c) estudia solo un hospital pediátrico y no es representativo de población adulta; además usa sexo y comuna como variables, que Prioriza no replica por criterios de equidad (CLAUDE.md).
- Barahona et al. (E4d) reporta suspensión de cirugía, no inasistencia pura; ~50% de suspensiones son por causas del paciente, no solo "no asistencia".

## Fuentes solo de contexto

| Fuente | Organismo / medio | URL | Motivo de no usarla como entrada |
|---|---|---|---|
| CIPER, 2026-09-29 | Prensa | [Informe subsecretaría](https://www.ciperchile.cl/2026/09/29/informe-de-la-subsecretaria-de-redes-asistenciales-muestra-aumento-de-listas-de-espera-para-intervenciones-quirurgicas-no-ges/) | Prensa: nunca dato de entrada. IQ no GES 412.834 (II-2026, +13,9% interanual) |
| Radio U. de Chile | Medios | — | Prensa: nunca dato de entrada |
| La Tercera, II-2024 | Prensa | — | Prensa: nunca dato de entrada |
| BioBioChile, 2025-02-27 | Prensa | — | Prensa: nunca dato de entrada (2.508.227 personas dic-2024) |
| U. de Chile, 2022-07-28 | Prensa institucional | — | Piloto en tres establecimientos: 20,3% → 12,5% con llamada; nota de prensa, no publicación |
| Glosa II-2026 (CIPER) | Copia no oficial | [Enlace](https://www.ciperchile.cl/wp-content/uploads/Glosa-06-LE-II-trimestre-2026-1-final-IQ.pdf) | Alojada en CIPER; pasa a ENTRADA solo si aparece en minsal.cl |
| BCN | Síntesis secundaria | — | Síntesis; sin acceso a datos brutos |
| DIPRES | Ley de Presupuestos | — | Define obligación de reporte, no trae cifras |
| Consejo para la Transparencia, 2025-03-17 | Consejo para la Transparencia | [Comunicado](https://www.consejotransparencia.cl/consejo-para-la-transparencia-advierte-deficiencias-en-acceso-a-informacion-sobre-listas-de-espera-en-el-sistema-de-salud-publica/) | Solo 7 de 29 servicios publican proactivamente; respalda la sección de vacíos |
| Revisiones internacionales (Dantas 2018, Koushan 2021, Greenup 2025) | Literatura | — | No verificadas en detalle o sin tasas desagregadas útiles por especialidad |
| DEIS y REM A04/A21 | Minsal | [Consultar](https://deis.minsal.cl/) | Candidatos; pendiente localizar descarga real y confirmar campos de inasistencia |

## Fuentes descartadas y no verificadas

**Descartadas:**
- Portal Paciente (requiere RUT/Clave Única, acceso a datos individuales)
- Ninguna fuente con microdatos de pacientes reales

**No verificadas (timeout o error al comprobar):**
- minsal.cl/publicaciones-institucionales-segun-ley-de-presupuesto/ (timeout 30 s; HTTP 500 durante la investigación)
- minsal.cl/eje-tiempos-de-espera/ (timeout 30 s; HTTP 500 durante la investigación)
- Glosas históricas 2017–2019 (vistas en buscador, no abiertas)
- camara.cl (HTTP 403)
- algoritmospublicos.cl (HTTP 404)

## Vacíos de datos

| # | Vacío | Impacto en Prioriza | Mitigación |
|---|---|---|---|
| 1 | No hay datos de listas de espera en formato abierto (CSV/API); solo PDF trimestrales (Glosa 06) y visores | Ingesta requiere parser de PDF y gestión manual de documentos | Parser en `ingestion/`; fixtures grabadas con SHA256 y URL; reproducibilidad mediante versionado |
| 2 | No hay inasistencia pública desagregada por servicio, especialidad, comuna, previsión o edad | Modelo de inasistencias debe calibrarse con tasas base históricas agregadas o por servicio (máximo Sepúlveda 2022) | Tasas base como parámetros explícitos (E4a, E4b); análisis de sensibilidad; posible solicitud por Ley de Transparencia |
| 3 | No hay tasa pública de inasistencia a cirugía; solo suspensiones con causas agregadas ("No se presenta" dentro de "administrativa") con cambio de clasificación en 2023 | Simulación de cirugías requiere asunción sobre inasistencia quirúrgica vs suspensión administrativa | Usar tasa Barahona (E4d) solo como rango ilustrativo; documentar limitación |
| 4 | Solo medianas, promedios y rangos de tiempos; no distribuciones individuales ni cuantiles | Generación de población sintética debe ajustar distribuciones paramétricas (lognormal/Weibull) sin datos granulares | Ajustar a mediana + promedio + rangos publicados; validar contra los rangos de espera publicados en la Glosa |
| 5 | Licencias no declaradas por Minsal/Superintendencia | Reutilización legal y práctica incierta | Citar la fuente; no redistribuir PDF en el repo (solo URL y SHA256); documentar alcance de uso en este proyecto |
| 6 | Series históricas heterogéneas (cambios de definición 2023, caídas de minsal.cl) | Imposible comparación directa antes/después 2023; confiabilidad de tendencias limitada | Documentar corte y definición de cada trimestre; no comparar causales de suspensión antes y después de 2023 |
| 7 | Desagregaciones por comuna para evaluación de equidad no publicadas para listas de espera | Validación de equidad debe asumir distribución de población sintética por comuna | La población sintética genera la distribución por comuna como supuesto explícito y reportado; se mide y reporta cualquier impacto desigual |

## Pendientes antes de cerrar la ingesta

- [ ] Extraer contenido de Glosa 06 IV-2025 (E2a) y confirmar que I-2026 (E2b) contiene desglose por servicio
- [ ] Abrir y revisar archivos XLSX de Superintendencia (E3)
- [ ] Revisar y documentar licencia específica del dataset de establecimientos en datos.gob.cl (E5)
- [ ] Localizar descarga de datos abiertos de DEIS y confirmar disponibilidad de campos REM A04 (no verificada)
- [ ] Reintentar conexión a índices de minsal.cl/publicaciones y minsal.cl/eje-tiempos
- [ ] Considerar solicitud por Ley de Transparencia para tasas de inasistencia desagregadas
