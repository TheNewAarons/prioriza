"""Configuración de los tests de la simulación (100 % sintéticos, sin red ni base de datos)."""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import settings

# Con --import-mode=importlib el directorio de tests no está en sys.path.
sys.path.insert(0, str(Path(__file__).parent))

# Semillas fijas también en hypothesis (CLAUDE.md).
settings.register_profile("simulation", derandomize=True, print_blob=True)
settings.load_profile("simulation")
