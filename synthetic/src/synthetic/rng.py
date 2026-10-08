"""Generadores aleatorios independientes por componente e identificadores deterministas."""

from enum import IntEnum
from uuid import UUID

import numpy as np


class Stream(IntEnum):
    """Identificador de flujo aleatorio: cada componente usa el suyo."""

    ALLOCATION = 1
    ATTRS = 2
    WAIT = 3
    PRIORITY = 4
    GES = 5
    LATENT = 6
    HISTORY = 7
    SPEC_EFFECTS = 8
    PATIENT_LINK = 9
    VALIDATION = 10  # sorteo independiente de u para el chequeo C6 no tautológico


def rng_for(seed: int, stream: Stream) -> np.random.Generator:
    """Generador PCG64 con ``SeedSequence(seed, spawn_key=(stream,))``."""
    seq = np.random.SeedSequence(seed, spawn_key=(int(stream),))
    return np.random.Generator(np.random.PCG64(seq))


def entity_uuid(run_id: UUID, kind: str, index: int) -> UUID:
    """UUID v5 determinista de una entidad: ``uuid5(run_id, "kind:index")``."""
    import uuid

    return uuid.uuid5(run_id, f"{kind}:{index}")
