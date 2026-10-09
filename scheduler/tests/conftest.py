"""Configuración de los tests del programador (100 % sintéticos, sin red ni base de datos)."""

from __future__ import annotations

import sys
from pathlib import Path

# Con --import-mode=importlib el directorio de tests no está en sys.path.
sys.path.insert(0, str(Path(__file__).parent))

from hypothesis import settings

# Semillas fijas también en hypothesis (CLAUDE.md): los @settings de cada test heredan esto.
settings.register_profile("scheduler", derandomize=True, print_blob=True)
settings.load_profile("scheduler")
