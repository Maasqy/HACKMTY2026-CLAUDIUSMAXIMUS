#!/usr/bin/env python3
"""
scripts/generar_segundo_caso.py — un SEGUNDO caso de prueba, a proposito
distinto del primero en todo lo que se ve en pantalla.

Los otros generadores (generar_ejemplo_proveedores.py y
generar_ejemplo_frontend.py) siembran siempre la misma historia: mismo
proveedor fantasma del 69-B, mismo kickback, mismas cuatro entidades. Eso
sirve para probar el pipeline, pero vuelve imposible contestar a ojo
"¿se actualizo el dashboard o estoy viendo la corrida anterior?" — dos
corridas distintas se ven identicas.

Este genera otra empresa, otros RFC y OTROS DOS ESQUEMAS:

  - THRESHOLD_SPLITTING: RFC:STD210615MN8 mete cuatro ordenes de compra de
    entre $46,800 y $49,100 — todas justo debajo del limite de autorizacion
    de $50,000 (APPROVAL_LIMIT_MXN), que sumadas lo rebasan de sobra.

  - ROUND_TRIPPING: el dinero sale de la empresa a RFC:CCP190722XB1, pasa a
    RFC:IFN200310QK3 y vuelve a la cuenta de la empresa en una semana. Sale
    y regresa: ninguna sustancia economica de por medio.

NO trae proveedor fantasma ni kickback. La lista 69-B se incluye con un RFC
real que NO es proveedor de esta empresa — el caso normal y correcto: que
la lista exista no acusa a nadie por si sola.

Uso:
    python3 scripts/generar_segundo_caso.py                 # -> segundo_caso/ (8 CSV) + segundo_caso.xlsx
    python3 scripts/generar_segundo_caso.py --salida otra/

Los CSV son para la pantalla Upload del frontend (columnas en ingles,
exactas). El .xlsx es para scripts/excel_a_estate.py (encabezados en
espanol, con alias).
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

COMPANY_RFC = "GIZ150220KL4"
COMPANY_NAME = "Grupo Industrial Zaragoza SA de CV"
COMPANY_CLABE = "002180005550001111"

# rfc, razon social, clabe, giro, alta
PROVEEDORES = [
    ("ACM980415TY2", "Aceros y Metales del Bajio SA de CV", "012180001111000001", "Insumos", "2018-03-12"),
    ("LPE050810RT9", "Logistica Peninsular SA de CV", "012180001111000002", "Transporte", "2019-07-22"),
    ("ECG111130UH5", "Energia y Climas del Golfo SC", "012180001111000003", "Mantenimiento", "2020-01-15"),
    # Fraccionamiento: cuatro POs pegadas al limite de autorizacion.
    ("STD210615MN8", "Suministros Tecnicos Delta SA de CV", "012180001111000004", "Insumos", "2024-06-15"),
    # Round-tripping: primer salto del ciclo.
    ("CCP190722XB1", "Corporativo Circular del Pacifico SA de CV", "012180001111000005", "Consultoria", "2023-07-22"),
    # Segundo salto: por donde el dinero regresa.
    ("IFN200310QK3", "Inversiones Fenix del Norte SA de CV", "012180001111000006", "Financiera", "2022-03-10"),
]

EMPLEADOS = [
    ("EMP:0101", "Mariana Otero Vidal", "Directora de Finanzas", "", "2017-05-02"),
    ("EMP:0102", "Hector Lomeli Prado", "Gerente de Adquisiciones", "", "2019-09-16"),
    ("EMP:0103", "Sofia Arreola Nunez", "Coordinadora de Proyectos", "", "2021-01-11"),
]

BASE = date(2026, 2, 2)


def _csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def construir_datos():
    """Arma las filas una sola vez; los dos formatos salen de aqui."""
    clabes = {p[0]: p[2] for p in PROVEEDORES}

    # --- facturas --------------------------------------------------------
    facturas: list[tuple[str, str, date, float, str]] = []
    folio = 1

    def inv(rfc: str, dia: int, subtotal: float, concepto: str) -> None:
        nonlocal folio
        facturas.append((f"A-{folio:04d}", rfc, BASE + timedelta(days=dia), subtotal, concepto))
        folio += 1

    inv("ACM980415TY2", 3, 184000.00, "Perfil de acero estructural, lote 412")
    inv("ACM980415TY2", 61, 162500.00, "Lamina galvanizada calibre 18, 400 piezas")
    inv("LPE050810RT9", 8, 74300.00, "Fletes Merida-Villahermosa, 22 viajes")
    inv("LPE050810RT9", 55, 68900.00, "Fletes Merida-Campeche, 19 viajes")
    inv("ECG111130UH5", 14, 96400.00, "Mantenimiento de sistema de enfriamiento, nave 2")
    # El del fraccionamiento: cada factura empata con una PO de las de abajo.
    inv("STD210615MN8", 10, 41810.34, "Herramienta neumatica, pedido parcial 1")
    inv("STD210615MN8", 17, 40689.66, "Herramienta neumatica, pedido parcial 2")
    inv("STD210615MN8", 24, 42327.59, "Herramienta neumatica, pedido parcial 3")
    inv("STD210615MN8", 31, 40344.83, "Herramienta neumatica, pedido parcial 4")
    # El del ciclo: una factura que justifica la salida de dinero.
    inv("CCP190722XB1", 40, 362068.97, "Consultoria de reestructura operativa")

    # --- transferencias ---------------------------------------------------
    txns: list[list] = []
    n = 1

    def txn(dia: int, origen: str, destino: str, monto: float, ref: str) -> None:
        nonlocal n
        txns.append([f"B-{n:04d}", (BASE + timedelta(days=dia)).isoformat(),
                    origen, destino, round(monto, 2), ref, "SPEI"])
        n += 1

    # Pagos normales: la empresa paga sus facturas 10 dias despues.
    for fid, rfc, fecha, subtotal, _c in facturas:
        if rfc in ("CCP190722XB1",):
            continue  # el del ciclo se paga abajo, como parte del ciclo
        dia = (fecha - BASE).days + 10
        txn(dia, COMPANY_CLABE, clabes[rfc], subtotal * 1.16, f"Pago {fid}")

    # EL CICLO: sale de la empresa, pasa por un tercero, y regresa.
    # trazar_pagos() encadena por CLABE destino -> CLABE origen dentro de 10
    # dias por salto; el detector exige >=3 saltos y que el ultimo cierre en
    # la CLABE de la empresa.
    txn(50, COMPANY_CLABE, clabes["CCP190722XB1"], 420000.00, "Pago A-0012 consultoria")
    txn(54, clabes["CCP190722XB1"], clabes["IFN200310QK3"], 405000.00, "Colocacion de excedentes")
    txn(57, clabes["IFN200310QK3"], COMPANY_CLABE, 395000.00, "Liquidacion de inversion")

    # --- ordenes de compra ------------------------------------------------
    pos: list[list] = []
    p = 1

    def po(rfc: str, dia: int, monto: float, solicita: str, aprueba: str, desc: str) -> None:
        nonlocal p
        pos.append([f"OC-{p:04d}", rfc, (BASE + timedelta(days=dia)).isoformat(),
                   round(monto, 2), solicita, aprueba, desc])
        p += 1

    # EL FRACCIONAMIENTO: cuatro POs entre $45,000 y $50,000 — cada una
    # pasa sola, las cuatro juntas rebasan el limite con creces.
    po("STD210615MN8", 9, 48500.00, "Hector Lomeli Prado", "Hector Lomeli Prado", "Herramienta neumatica, parcial 1")
    po("STD210615MN8", 16, 47200.00, "Hector Lomeli Prado", "Hector Lomeli Prado", "Herramienta neumatica, parcial 2")
    po("STD210615MN8", 23, 49100.00, "Hector Lomeli Prado", "Hector Lomeli Prado", "Herramienta neumatica, parcial 3")
    po("STD210615MN8", 30, 46800.00, "Hector Lomeli Prado", "Hector Lomeli Prado", "Herramienta neumatica, parcial 4")
    # Compras normales: montos altos, aprobadas por alguien distinto al solicitante.
    po("ACM980415TY2", 2, 213440.00, "Sofia Arreola Nunez", "Mariana Otero Vidal", "Acero estructural, lote 412")
    po("ACM980415TY2", 60, 188500.00, "Sofia Arreola Nunez", "Mariana Otero Vidal", "Lamina galvanizada")
    po("LPE050810RT9", 7, 86188.00, "Hector Lomeli Prado", "Mariana Otero Vidal", "Fletes del trimestre")
    po("ECG111130UH5", 13, 111824.00, "Sofia Arreola Nunez", "Mariana Otero Vidal", "Mantenimiento nave 2")

    # --- contratos --------------------------------------------------------
    contratos = [
        ["CT-0001", "ACM980415TY2", "2018-03-12", 2400000.00, "Suministro anual de acero"],
        ["CT-0002", "LPE050810RT9", "2019-07-22", 890000.00, "Fletes foraneos, contrato marco"],
        ["CT-0003", "ECG111130UH5", "2020-01-15", 640000.00, "Mantenimiento industrial anual"],
        ["CT-0005", "CCP190722XB1", "2023-07-22", 720000.00, "Consultoria de reestructura"],
    ]

    return facturas, txns, pos, contratos, clabes


def construir(salida: Path, xlsx: Path | None) -> None:
    facturas, txns, pos, contratos, _clabes = construir_datos()

    # --- los 8 CSV para el importador del frontend -----------------------
    _csv(salida / "vendors.csv",
         ["rfc", "legal_name", "registered_date", "address", "bank_clabe", "category", "contact_email"],
         [[rfc, nombre, alta, "", clabe, giro, ""] for rfc, nombre, clabe, giro, alta in PROVEEDORES])

    _csv(salida / "invoices.csv",
         ["uuid", "issuer_rfc", "receiver_rfc", "issue_date", "subtotal", "iva", "total",
          "concepto_text", "uso_cfdi", "forma_pago", "metodo_pago", "status"],
         [[fid, rfc, COMPANY_RFC, fecha.isoformat(), sub, round(sub * 0.16, 2),
           round(sub * 1.16, 2), concepto, "G03", "TRANSFERENCIA", "PUE", "vigente"]
          for fid, rfc, fecha, sub, concepto in facturas])

    _csv(salida / "bank_txns.csv",
         ["txn_id", "date", "from_clabe", "to_clabe", "amount", "reference", "channel"],
         txns)

    _csv(salida / "purchase_orders.csv",
         ["po_id", "vendor_rfc", "date", "amount", "requester", "approver", "description"],
         pos)

    _csv(salida / "contracts.csv",
         ["contract_id", "vendor_rfc", "start_date", "value", "scope_text"],
         contratos)

    _csv(salida / "employees.csv",
         ["emp_id", "name", "role", "bank_clabe", "hire_date"],
         [list(e) for e in EMPLEADOS])

    # Un RFC real del 69-B que NO es proveedor de esta empresa: la lista
    # existe, y correctamente no acusa a nadie aqui.
    _csv(salida / "efos_list.csv",
         ["rfc", "legal_name", "status", "publication_date"],
         [["AAA120730823", "ASESORES Y ADMINISTRADORES AGRICOLAS, S. DE R.L. DE C.V.",
           "definitivo", "2017-01-19"]])

    ledger: list[list] = []
    e = 1
    for fid, rfc, fecha, sub, _c in facturas:
        total = round(sub * 1.16, 2)
        nombre = next(n for r, n, *_ in PROVEEDORES if r == rfc)
        ledger.append([e, fecha.isoformat(), "5100", "Costo de ventas", total, 0,
                       f"Factura {fid} — {nombre}", fid, "PLANTA", "Mariana Otero Vidal"])
        e += 1
        ledger.append([e, fecha.isoformat(), "2010", "Proveedores por pagar", 0, total,
                       f"Factura {fid} — {nombre}", fid, "PLANTA", "Mariana Otero Vidal"])
        e += 1
    _csv(salida / "ledger.csv",
         ["entry_id", "date", "account_code", "account_name", "debit", "credit",
          "description", "invoice_uuid", "cost_center", "approver"],
         ledger)

    # --- el .xlsx para scripts/excel_a_estate.py -------------------------
    if xlsx is not None:
        try:
            from openpyxl import Workbook
        except ImportError:
            print("(sin openpyxl: no se escribio el .xlsx, los CSV si)")
        else:
            wb = Workbook()
            wb.remove(wb.active)

            ws = wb.create_sheet("Proveedores")
            ws.append(["RFC", "Razon Social", "CLABE", "Giro", "Fecha de Alta"])
            for p in PROVEEDORES:
                ws.append(list(p))

            ws = wb.create_sheet("Empleados")
            ws.append(["ID", "Nombre", "Puesto", "CLABE", "Fecha de Ingreso"])
            for emp in EMPLEADOS:
                ws.append(list(emp))

            ws = wb.create_sheet("Facturas")
            ws.append(["Folio", "RFC Emisor", "RFC Receptor", "Fecha de Emision",
                       "Subtotal", "Concepto", "Metodo de Pago", "Estatus"])
            for fid, rfc, fecha, sub, concepto in facturas:
                ws.append([fid, rfc, COMPANY_RFC, fecha.isoformat(), sub, concepto, "PUE", "vigente"])

            ws = wb.create_sheet("Transferencias")
            ws.append(["Folio", "Fecha", "CLABE Origen", "CLABE Destino", "Monto", "Referencia", "Canal"])
            for t in txns:
                ws.append(t)

            ws = wb.create_sheet("Ordenes de Compra")
            ws.append(["Orden", "RFC Proveedor", "Fecha", "Monto", "Solicitante", "Aprobador", "Descripcion"])
            for o in pos:
                ws.append(o)

            ws = wb.create_sheet("Contratos")
            ws.append(["Contrato", "RFC Proveedor", "Fecha de Inicio", "Valor", "Alcance"])
            for c in contratos:
                ws.append(c)

            xlsx.parent.mkdir(parents=True, exist_ok=True)
            wb.save(xlsx)

    print(f"Escrito en: {salida}/")
    for nombre in ("vendors", "invoices", "ledger", "bank_txns", "purchase_orders",
                   "contracts", "employees", "efos_list"):
        filas = sum(1 for _ in (salida / f"{nombre}.csv").open(encoding="utf-8")) - 1
        print(f"  {nombre}.csv  ({filas} filas)")
    if xlsx is not None and xlsx.exists():
        print(f"Escrito: {xlsx}")

    print(f"\nEmpresa: {COMPANY_NAME}  ({COMPANY_RFC})")
    print("Casos sembrados, DISTINTOS a los del primer juego de datos:")
    print("  RFC:STD210615MN8  threshold_splitting  (4 POs de $46,800-$49,100, bajo el limite de $50,000)")
    print("  RFC:CCP190722XB1  round_tripping       (el dinero sale y regresa en 7 dias)")
    print("  (sin proveedor fantasma y sin kickback, a diferencia del primer caso)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path("segundo_caso"))
    ap.add_argument("--xlsx", type=Path, default=Path("segundo_caso.xlsx"))
    ap.add_argument("--sin-xlsx", action="store_true")
    args = ap.parse_args()
    construir(args.salida, None if args.sin_xlsx else args.xlsx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
