"""
src/api.py — servidor local que le da al frontend acceso al pipeline.

POR QUE EXISTE. El frontend construia el estate y ahi se rendia: te
descargaba un .db y te mandaba a una terminal a correr Python, copiar un
JSON a mano y recargar la pagina. La investigacion — la parte que importa —
quedaba fuera del producto, y nada de lo que subias volvia a aparecer.

Esto NO mueve el pipeline al navegador. Gemma corre local en Ollama y las
etapas deterministas son Python; eso no cambia. Lo unico que cambia es que
el pipeline queda expuesto por HTTP para que el flujo sea uno solo:

    subir CSVs -> construir estate -> INVESTIGAR -> ver hallazgos verificables

    python3 -m src.api                 # escucha en http://127.0.0.1:8000

POR QUE BIBLIOTECA ESTANDAR Y NO FASTAPI. requirements.txt presume de una
sola dependencia de runtime (requests, para hablar con Ollama) y eso no es
presumir por presumir: es lo que permite replicar una corrida en la maquina
de un juez sin instalar nada pesado. Meter fastapi + uvicorn + pydantic por
tres endpoints cambiaria esa propiedad por comodidad. http.server sirve de
sobra para un servidor local de un solo usuario.

Se escucha SOLO en 127.0.0.1: esto lee y escribe archivos de tu repo y
corre el pipeline a peticion, asi que no tiene nada que hacer expuesto a la
red. Tampoco tiene autenticacion, precisamente porque no debe salir de ahi.

La investigacion tarda minutos (un modelo de 12B local, varios turnos por
lead), asi que no se responde de golpe: POST /api/investigate arranca un
trabajo y devuelve su id, y GET /api/jobs/{id} entrega el progreso en vivo
— las mismas lineas que imprime `python3 -m src.run`. Un navegador esperando
tres minutos a un POST sin senales de vida es exactamente el "parece
colgado" que ya nos costo una sesion entera.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests

from src.config import LLM_BASE_URL, LLM_MODEL
from src.forensic.client import LLMClient
from src.pipeline import ejecutar
from src.tools import EstateDB

REPO_ROOT = Path(__file__).resolve().parent.parent
# Donde el frontend lee el submission cuando no hay servidor. Se sigue
# escribiendo para que un reload conserve los hallazgos y para que el flujo
# por terminal siga funcionando igual.
SNAPSHOT_DIR = REPO_ROOT / "frontend" / "public" / "out"

# Origenes del dev server de Vite. Sin esto el navegador bloquea cada
# llamada; con una lista cerrada, cualquier otra pagina que intente hablarle
# a este servidor se queda fuera.
ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
}

MAX_ESTATE_BYTES = 256 * 1024 * 1024
SQLITE_MAGIC = b"SQLite format 3\x00"


@dataclass
class Job:
    id: str
    status: str = "running"          # running | done | error
    progress: list[str] = field(default_factory=list)
    submission: Optional[dict] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _persist(submission: dict) -> None:
    """Deja el submission donde el frontend lo lee sin servidor.

    Es lo que hacia `scripts/refresh_frontend_snapshots.sh` a mano. Que
    falle no tumba el trabajo: el resultado ya se entrega por HTTP.
    """
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / "submission.json").write_text(
            json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8",
        )
    except OSError:
        pass


def _run_job(job: Job, db_path: Path, max_leads: int, sin_modelo: bool, offline: bool) -> None:
    try:
        def progreso(texto: str) -> None:
            with _LOCK:
                job.progress.append(f"[{time.time() - job.started_at:6.1f}s] {texto}")

        client = None if sin_modelo else LLMClient(offline=offline)
        with EstateDB(db_path) as estate:
            submission = ejecutar(estate, client, max_leads=max_leads, on_progress=progreso)

        submission["seed"] = 0
        submission["run_metadata"].setdefault("cost_by_role", {})

        with _LOCK:
            job.submission = submission
            job.status = "done"
            job.finished_at = time.time()
        _persist(submission)
    except Exception as exc:                      # noqa: BLE001 — se reporta, no se traga
        with _LOCK:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = time.time()
    finally:
        db_path.unlink(missing_ok=True)


def _health() -> dict:
    """Si Ollama esta arriba y si el modelo configurado esta instalado.

    La UI lo consulta ANTES de dejarte arrancar: enterarte de que el modelo
    no estaba a los tres minutos, con cero hallazgos y sin explicacion, es
    la peor forma de descubrirlo.
    """
    reachable = False
    instalados: list[str] = []
    detalle = ""
    try:
        r = requests.get(f"{LLM_BASE_URL.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        instalados = [m.get("name", "") for m in r.json().get("models", [])]
        reachable = True
    except requests.RequestException as exc:
        detalle = str(exc)

    return {
        "ok": True,
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
        "ollama_reachable": reachable,
        "model_installed": LLM_MODEL in instalados,
        "models_installed": instalados,
        "detail": detalle,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "FraudForensics/1.0"

    # --- plomeria ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        # Una linea por peticion, legible, en vez del formato de CGI.
        print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, detalle: str) -> None:
        self._json({"error": detalle}, status=status)

    def do_OPTIONS(self) -> None:           # noqa: N802 — nombre que exige http.server
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    # --- rutas ------------------------------------------------------------

    def do_GET(self) -> None:               # noqa: N802
        parsed = urlparse(self.path)
        ruta = parsed.path

        if ruta == "/api/health":
            self._json(_health())
            return

        if ruta.startswith("/api/jobs/"):
            job_id = ruta[len("/api/jobs/"):].strip("/")
            params = parse_qs(parsed.query)
            try:
                desde = int(params.get("desde", ["0"])[0])
            except ValueError:
                desde = 0
            with _LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    self._error(404, "No existe ese trabajo.")
                    return
                elapsed = (job.finished_at or time.time()) - job.started_at
                payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "progress": job.progress[max(desde, 0):],
                    "progress_total": len(job.progress),
                    "elapsed_seconds": round(elapsed, 1),
                    "submission": job.submission,
                    "error": job.error,
                }
            self._json(payload)
            return

        self._error(404, f"Ruta desconocida: {ruta}")

    def do_POST(self) -> None:              # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/investigate":
            self._error(404, f"Ruta desconocida: {parsed.path}")
            return

        try:
            largo = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            largo = 0
        if largo <= 0:
            self._error(400, "El estate llego vacio.")
            return
        if largo > MAX_ESTATE_BYTES:
            self._error(413, f"El estate excede {MAX_ESTATE_BYTES // (1024 * 1024)} MB.")
            return

        data = self.rfile.read(largo)
        # El cuerpo es el .db crudo (application/octet-stream): sin multipart
        # no hace falta parsear nada ni instalar python-multipart.
        if not data.startswith(SQLITE_MAGIC):
            self._error(400, "Ese archivo no es una base SQLite valida.")
            return

        params = parse_qs(parsed.query)

        def flag(nombre: str) -> bool:
            return params.get(nombre, ["0"])[0] in ("1", "true", "True")

        try:
            max_leads = int(params.get("max_leads", ["4"])[0])
        except ValueError:
            max_leads = 4
        max_leads = max(1, min(max_leads, 100))

        fd = tempfile.NamedTemporaryFile(prefix="estate_", suffix=".db", delete=False)
        try:
            fd.write(data)
        finally:
            fd.close()

        job = Job(id=uuid.uuid4().hex[:12])
        with _LOCK:
            _JOBS[job.id] = job

        threading.Thread(
            target=_run_job,
            args=(job, Path(fd.name), max_leads, flag("sin_modelo"), flag("offline")),
            daemon=True,
        ).start()

        self._json({"job_id": job.id, "status": job.status})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="solo loopback por default; este servidor no lleva "
                        "autenticacion y corre el pipeline a peticion")
    args = ap.parse_args()

    servidor = ThreadingHTTPServer((args.host, args.port), Handler)
    salud = _health()
    print(f"Fraud Forensics API  ->  http://{args.host}:{args.port}")
    print(f"  modelo configurado : {salud['model']}")
    if not salud["ollama_reachable"]:
        print(f"  Ollama             : NO responde en {salud['base_url']}")
        print("                       levantalo con `ollama serve` antes de investigar")
    elif not salud["model_installed"]:
        print(f"  Ollama             : arriba, pero {salud['model']} no esta instalado")
        print(f"                       instalados: {', '.join(salud['models_installed']) or 'ninguno'}")
    else:
        print("  Ollama             : arriba, con el modelo instalado")
    print("\nCtrl+C para parar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nAdios.")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
