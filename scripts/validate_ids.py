#!/usr/bin/env python3
"""Valida que los identificadores citados en outputs existan en el patrimonio cargado.

Hook PostToolUse. Sale con codigo 2 y mensaje en stderr si encuentra un id inventado,
lo que hace que Claude Code muestre el error al agente y lo obligue a corregir.

Estado: ESQUELETO. Implementar la carga real del patrimonio antes de confiar en el.
"""
import json
import pathlib
import re
import sys

CASEFILE_DIR = pathlib.Path("demo/output")
ESTATE_DIR = pathlib.Path("data/synthetic")

UUID_RE = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
RFC_RE = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")


def known_ids() -> set[str]:
    ids: set[str] = set()
    if not ESTATE_DIR.exists():
        return ids
    for csv_path in ESTATE_DIR.rglob("*.csv"):
        text = csv_path.read_text(encoding="utf-8", errors="ignore")
        ids.update(UUID_RE.findall(text))
        ids.update(RFC_RE.findall(text))
    return ids


def main() -> int:
    if not CASEFILE_DIR.exists():
        return 0
    known = known_ids()
    if not known:
        return 0

    invented: list[tuple[str, str]] = []
    for path in CASEFILE_DIR.rglob("*.json"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for found in set(UUID_RE.findall(text)) | set(RFC_RE.findall(text)):
            if found not in known:
                invented.append((str(path), found))

    if invented:
        print("Identificadores que NO existen en el patrimonio:", file=sys.stderr)
        for path, ident in invented[:20]:
            print(f"  {path}: {ident}", file=sys.stderr)
        print("Corrige el output: no se puede citar evidencia inexistente.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
