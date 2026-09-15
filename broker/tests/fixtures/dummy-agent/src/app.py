"""
Agente externo de mentira -- FastAPI mínima, descartable. Nadie que
construyó el Broker tocó este código a propósito (más allá de este
comentario): es la señal más fuerte de portabilidad real -- si esto
instala y arranca por el mecanismo genérico, el mecanismo es genérico
de verdad, no solo "funciona con kal-in porque lo escribimos pensando
en kal-in".
"""
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"agent": "dummy-agent"}


@app.get("/echo/{text}")
def echo(text: str) -> dict:
    return {"echo": text}
