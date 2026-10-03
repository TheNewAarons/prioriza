"""Aplicación FastAPI mínima de Prioriza."""

from fastapi import FastAPI

app = FastAPI(title="Prioriza API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Sonda de salud para Docker y orquestadores."""
    return {"status": "ok"}
