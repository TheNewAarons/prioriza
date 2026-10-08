"""Modelo de predicción de inasistencias para Prioriza.

Modelo calibrado de scikit-learn que estima la probabilidad de que un paciente no se presente
a su cita o cirugía, sin usar atributos protegidos ni proxies evidentes (ver
``noshow.features``). Herramienta de investigación con datos sintéticos. No usar para
decisiones clínicas ni de gestión real sin validación institucional.
"""

MODEL_FORMAT_VERSION = "1"
