#!/usr/bin/env python3
"""
scripts/construir_submission_demo.py — arma un submission.json de ejemplo
CON findings reales Y leads_not_pursued reales, sin depender de que Ollama
este corriendo.

Por que existe: `python3 -m src.run --sin-modelo` SIEMPRE produce
findings=0 (sin investigador no hay draft que validar, por diseno del
pipeline -- ver src/pipeline.py). Eso es correcto para el pipeline real,
pero deja las pantallas de Case Files y Overview del frontend sin nada que
mostrar en una demo si no tienes Gemma/Ollama levantado.

Este script NO inventa evidencia ni cifras: arma los mismos FindingDraft
que un investigador real habria producido para los 4 leads sembrados en
scripts/generar_ejemplo_frontend.py (kickback + phantom_vendor + dos leads
sin fraude), y los pasa por el `validar()` y `construir_money_trail()`
REALES del pipeline (src/forensic/validator.py, src/forensic/money_trail.py)
contra la estate real -- si algun record_id fuera invento o el monto no
reconciliara, este script fallaria igual que fallaria un run real. Lo que
sale ya paso por la misma puerta que pasa cualquier finding genuino.

Uso:
    python3 scripts/generar_ejemplo_frontend.py --salida /tmp/caso1
    python3 scripts/excel_a_estate.py --entrada /tmp/caso1 --salida /tmp/caso1.db
    python3 scripts/construir_submission_demo.py --estate /tmp/caso1.db --out frontend/public/out/submission.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.forensic.investigator import FindingDraft
from src.forensic.money_trail import construir as construir_money_trail
from src.forensic.validator import validar
from src.metrics.run_metrics import RunMetrics
from src.tools import EstateDB


def _finding_kickback(estate) -> dict:
    exhibits = [
        {"exhibit_id": "EX-01", "source_table": "bank_txns", "record_id": "T-0012",
         "note": "Pago de la empresa a Servicios Preferentes de Ponente por la factura F-0012."},
        {"exhibit_id": "EX-02", "source_table": "bank_txns", "record_id": "T-0015",
         "note": "5 dias despues, el proveedor transfiere a la CLABE personal del empleado Ricardo Elizondo Sada, etiquetado 'Reembolso de gastos'."},
        {"exhibit_id": "EX-03", "source_table": "bank_txns", "record_id": "T-0013",
         "note": "Segundo pago de la empresa al mismo proveedor, factura F-0013."},
        {"exhibit_id": "EX-04", "source_table": "bank_txns", "record_id": "T-0016",
         "note": "Segunda retransferencia del proveedor al mismo empleado, mismo patron de 5 dias."},
        {"exhibit_id": "EX-05", "source_table": "bank_txns", "record_id": "T-0014",
         "note": "Tercer pago de la empresa al proveedor, factura F-0014."},
        {"exhibit_id": "EX-06", "source_table": "bank_txns", "record_id": "T-0017",
         "note": "Tercera retransferencia del proveedor al empleado, cierra el patron trimestral."},
        {"exhibit_id": "EX-07", "source_table": "purchase_orders", "record_id": "PO-0001",
         "note": "Ricardo Elizondo Sada aparece como solicitante Y aprobador de la orden de compra a este proveedor."},
        {"exhibit_id": "EX-08", "source_table": "employees", "record_id": "EMP:0007",
         "note": "Empleado que aprueba las compras a este proveedor y recibe las retransferencias."},
    ]
    peso_amount = round(136880.0 + 112984.0 + 98484.0 + 116348.0 + 96036.4 + 83711.4, 2)
    narrative = (
        "El proveedor Servicios Preferentes de Ponente (RFC:SVP200815KL9) recibio tres pagos "
        "de la empresa entre febrero y mayo de 2026 por asesoria estrategica trimestral. Cada "
        "vez, entre 3 y 5 dias despues, el proveedor transfirio una parte de ese dinero a la "
        "cuenta personal del empleado Ricardo Elizondo Sada (Gerente de Compras), etiquetada "
        "'Reembolso de gastos' -- un concepto que no corresponde a una relacion proveedor-empleado. "
        "Ricardo ademas aparece como solicitante Y aprobador de las tres ordenes de compra a este "
        "mismo proveedor, sin segregacion de funciones. El patron se repite identico tres veces "
        "seguidas, lo que descarta un reembolso aislado."
    )
    draft = FindingDraft(
        entity="RFC:SVP200815KL9",
        es_fraude=True,
        scheme_type="kickback",
        entities=("RFC:SVP200815KL9", "EMP:0007"),
        narrative=narrative,
        rule_broken="Codigo de conducta interno: conflicto de interes no revelado y ausencia de "
                    "segregacion de funciones (mismo empleado solicita y aprueba la compra al "
                    "proveedor del que luego recibe fondos).",
        peso_amount=peso_amount,
        exhibits=tuple(exhibits),
        confidence="proven",
        reason_if_not="",
        tool_calls_made=("obtener_ordenes_compra", "obtener_transferencias", "resolver_clabe",
                          "obtener_proveedor"),
    )
    v = validar(estate, draft)
    assert v.ok, f"kickback no valido: {v.resumen}"
    trail = construir_money_trail(estate, exhibits, company=estate.identificar_empresa())
    return {
        "scheme_type": draft.scheme_type,
        "entities": list(draft.entities),
        "narrative": draft.narrative,
        "rule_broken": draft.rule_broken,
        "peso_amount": draft.peso_amount,
        "exhibits": exhibits,
        "money_trail": trail,
        "confidence": draft.confidence,
    }, v


def _finding_phantom(estate) -> dict:
    exhibits = [
        {"exhibit_id": "EX-01", "source_table": "efos_list", "record_id": "AAA120730823",
         "note": "RFC en el listado 69-B del SAT con status 'definitivo': operaciones simuladas confirmadas por el gobierno, publicado 2017-01-19."},
        {"exhibit_id": "EX-02", "source_table": "invoices", "record_id": "F-0009",
         "note": "Factura con concepto generico 'Servicios profesionales diversos', sin detalle de que se compro."},
        {"exhibit_id": "EX-03", "source_table": "invoices", "record_id": "F-0010",
         "note": "Segunda factura, mismo patron de concepto generico."},
        {"exhibit_id": "EX-04", "source_table": "invoices", "record_id": "F-0011",
         "note": "Tercera factura, mismo patron de concepto generico."},
        {"exhibit_id": "EX-05", "source_table": "bank_txns", "record_id": "T-0009",
         "note": "La empresa SI pago esta factura pese a que el emisor esta confirmado como fantasma."},
        {"exhibit_id": "EX-06", "source_table": "bank_txns", "record_id": "T-0010",
         "note": "Segundo pago real a un proveedor sin sustancia economica confirmada por el SAT."},
        {"exhibit_id": "EX-07", "source_table": "bank_txns", "record_id": "T-0011",
         "note": "Tercer pago real al mismo proveedor fantasma."},
        {"exhibit_id": "EX-08", "source_table": "vendors", "record_id": "AAA120730823",
         "note": "Proveedor dado de alta sin una sola orden de compra ni contrato que respalde sus facturas."},
    ]
    peso_amount = round(111360.0 + 101500.0 + 105792.0, 2)
    narrative = (
        "Asesores y Administradores Agricolas (RFC:AAA120730823) aparece en el listado 69-B del "
        "SAT con status 'definitivo' -- el SAT confirmo que sus operaciones son simuladas. Pese a "
        "eso, la empresa le pago tres facturas por un total de $318,652.00 MXN entre enero y abril "
        "de 2026, todas con conceptos genericos ('servicios profesionales diversos', 'consultoria "
        "general') y sin una sola orden de compra ni contrato que respalde de que se trataba el "
        "servicio. No existe ninguna evidencia documental de que el trabajo facturado se haya "
        "realizado."
    )
    draft = FindingDraft(
        entity="RFC:AAA120730823",
        es_fraude=True,
        scheme_type="phantom_vendor",
        entities=("RFC:AAA120730823",),
        narrative=narrative,
        rule_broken="Art. 69-B del Codigo Fiscal de la Federacion: operaciones con un "
                    "contribuyente confirmado por el SAT como emisor de comprobantes que "
                    "simulan operaciones inexistentes (EFOS 'definitivo').",
        peso_amount=peso_amount,
        exhibits=tuple(exhibits),
        confidence="proven",
        reason_if_not="",
        tool_calls_made=("esta_en_lista_69b", "obtener_facturas", "perfil_proveedor",
                          "obtener_transferencias"),
    )
    v = validar(estate, draft)
    assert v.ok, f"phantom_vendor no valido: {v.resumen}"
    trail = construir_money_trail(estate, exhibits, company=estate.identificar_empresa())
    return {
        "scheme_type": draft.scheme_type,
        "entities": list(draft.entities),
        "narrative": draft.narrative,
        "rule_broken": draft.rule_broken,
        "peso_amount": draft.peso_amount,
        "exhibits": exhibits,
        "money_trail": trail,
        "confidence": draft.confidence,
    }, v


def _leads_not_pursued() -> list[dict]:
    return [
        {
            "entity": "EMP:0007",
            "signal": "kickback",
            "reason": "La transferencia de este empleado ya quedo documentada como parte del "
                      "mismo hecho investigado bajo RFC:SVP200815KL9 (ver ese finding); no se "
                      "abre un segundo hallazgo por la misma retransferencia de fondos.",
            "tool_calls_made": ["obtener_transferencias", "resolver_clabe"],
            "closed_by": "investigator",
        },
        {
            "entity": "RFC:PAP110603RE5",
            "signal": "sin_respaldo",
            "reason": "Dos facturas de papeleria (consumibles de oficina, $9,744 y $10,556 MXN) "
                      "sin orden de compra ni contrato formal, pero por debajo del umbral de "
                      "aprobacion y consistentes con la politica de gasto menor de la empresa. "
                      "Sin conceptos genericos, sin retransferencias, sin listado 69-B. No se "
                      "encontro evidencia de simulacion.",
            "tool_calls_made": ["perfil_proveedor", "obtener_facturas", "obtener_ordenes_compra",
                                "esta_en_lista_69b"],
            "closed_by": "investigator",
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with EstateDB(args.estate) as estate:
        f1, v1 = _finding_kickback(estate)
        f2, v2 = _finding_phantom(estate)

    m = RunMetrics()
    m.leads_generados = 4
    m.leads_investigados = 4
    m.findings_finales = 2
    submission = {
        "seed": args.seed,
        "findings": [f1, f2],
        "leads_not_pursued": _leads_not_pursued(),
        "run_metadata": m.as_run_metadata(None),
    }
    submission["run_metadata"].setdefault("cost_by_role", {})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(submission, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.out}  findings={len(submission['findings'])}  "
          f"leads_not_pursued={len(submission['leads_not_pursued'])}")
    print(f"  kickback:  {v1.resumen}")
    print(f"  phantom:   {v2.resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
