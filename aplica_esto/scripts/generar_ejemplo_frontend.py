#!/usr/bin/env python3
"""
scripts/generar_ejemplo_frontend.py — el MISMO caso de prueba que
scripts/generar_ejemplo_proveedores.py, pero partido en los 8 archivos
CSV por tabla que espera el importador del FRONTEND (frontend/src/lib/
estateSchema.ts, pantalla "Upload"), con los nombres de columna exactos en
ingles que ese importador exige (sin alias, a diferencia de
scripts/excel_a_estate.py, que es mas permisivo).

Dos casos sembrados a proposito, iguales al generador anterior:
  - PHANTOM_VENDOR: RFC:AAA120730823 — RFC REAL del listado 69-B del SAT
    ("Definitivo"), facturando conceptos genericos, sin PO ni contrato.
  - KICKBACK: RFC:SVP200815KL9 — factura normal, pero el proveedor
    retransfiere ~85% del pago a EMP:0007 (Ricardo Elizondo Sada), que es
    quien aprueba (y solicita) todas sus ordenes de compra.

Uso:
    python3 scripts/generar_ejemplo_frontend.py
    python3 scripts/generar_ejemplo_frontend.py --salida otra_carpeta/

Con la carpeta en mano: en la pantalla Upload del frontend, sube cada CSV
en su casilla correspondiente (Vendors, Invoices, Ledger, Bank
transactions, Purchase orders, Contracts, Employees, SAT 69-B list) y da
"Build estate".
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

COMPANY_RFC = "EMP920101AB1"
COMPANY_CLABE = "012180001234567890"
CLABE_EMPLEADO = "127180001112223334"

PROVEEDORES = [
    # rfc, legal_name, bank_clabe, category, registered_date
    ("CFL180312AB3", "Consultoria Fiscal del Levante SA de CV", "014180009876543210", "Consultoria", "2022-04-10"),
    ("MRN150920TU8", "Mantenimiento Regional del Norte SC", "021180003344556677", "Mantenimiento", "2021-08-01"),
    ("TLC090114QW2", "Transportes y Logistica del Centro SA de CV", "072180001122334455", "Transporte", "2020-02-15"),
    ("PAP110603RE5", "Papeleria y Suministros PROOFICE SA de CV", "044180005566778899", "Papeleria", "2019-11-20"),
    # Fantasma: RFC REAL del 69-B ("Definitivo").
    ("AAA120730823", "Asesores y Administradores Agricolas SA", "058180001231231234", "Consultoria", "2026-01-05"),
    # Kickback: factura normal, pero el pago se retransfiere al aprobador.
    ("SVP200815KL9", "Servicios Preferentes de Ponente SA de CV", "127180009998887776", "Consultoria", "2025-09-12"),
]


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def construir(salida: Path) -> None:
    clabes = {p[0]: p[2] for p in PROVEEDORES}
    base = date(2026, 1, 15)

    # -- vendors ----------------------------------------------------------
    vendors_rows = [[rfc, nombre, alta, "", clabe, giro, ""]
                    for rfc, nombre, clabe, giro, alta in PROVEEDORES]
    _write_csv(salida / "vendors.csv",
              ["rfc", "legal_name", "registered_date", "address", "bank_clabe",
               "category", "contact_email"],
              vendors_rows)

    # -- invoices -----------------------------------------------------------
    facturas: list[tuple[str, str, date, float]] = []
    folio = 1

    def add_inv(rfc, fecha, subtotal, concepto):
        nonlocal folio
        fid = f"F-{folio:04d}"
        iva = round(subtotal * 0.16, 2)
        total = round(subtotal + iva, 2)
        facturas.append((fid, rfc, fecha, subtotal))
        folio += 1
        return [fid, rfc, COMPANY_RFC, fecha.isoformat(), subtotal, iva, total,
               concepto, "G03", "TRANSFERENCIA", "PUE", "vigente"]

    invoice_rows = [
        add_inv("CFL180312AB3", base, 42000.00, "Dictamen fiscal ejercicio 2025"),
        add_inv("CFL180312AB3", base + timedelta(days=45), 38500.00, "Revision de nomina Q1 2026"),
        add_inv("MRN150920TU8", base + timedelta(days=5), 61200.00, "Mantenimiento preventivo planta Monterrey"),
        add_inv("MRN150920TU8", base + timedelta(days=70), 58900.00, "Reparacion compresor linea 2"),
        add_inv("TLC090114QW2", base + timedelta(days=10), 27300.00, "Flete Monterrey-Saltillo, 12 viajes"),
        add_inv("TLC090114QW2", base + timedelta(days=40), 31150.00, "Flete Monterrey-Reynosa, 14 viajes"),
        add_inv("PAP110603RE5", base + timedelta(days=20), 8400.00, "Consumibles de oficina marzo"),
        add_inv("PAP110603RE5", base + timedelta(days=80), 9100.00, "Consumibles de oficina mayo"),
        add_inv("AAA120730823", base + timedelta(days=8), 96000.00, "Servicios profesionales diversos"),
        add_inv("AAA120730823", base + timedelta(days=38), 87500.00, "Servicios de consultoria general"),
        add_inv("AAA120730823", base + timedelta(days=66), 91200.00, "Honorarios por servicios prestados"),
        add_inv("SVP200815KL9", base + timedelta(days=12), 118000.00, "Asesoria estrategica primer trimestre"),
        add_inv("SVP200815KL9", base + timedelta(days=52), 97400.00, "Asesoria estrategica segundo trimestre"),
        add_inv("SVP200815KL9", base + timedelta(days=95), 84900.00, "Asesoria estrategica tercer trimestre"),
    ]
    _write_csv(salida / "invoices.csv",
              ["uuid", "issuer_rfc", "receiver_rfc", "issue_date", "subtotal", "iva",
               "total", "concepto_text", "uso_cfdi", "forma_pago", "metodo_pago", "status"],
              invoice_rows)

    # -- bank_txns ------------------------------------------------------
    txn = 1
    txn_rows: list[list] = []

    def add_txn(fecha, origen, destino, monto, ref):
        nonlocal txn
        txn_rows.append([f"T-{txn:04d}", fecha.isoformat(), origen, destino, monto, ref, "SPEI"])
        txn += 1

    for fid, rfc, fecha, subtotal in facturas:
        total = round(subtotal * 1.16, 2)
        add_txn(fecha + timedelta(days=10), COMPANY_CLABE, clabes[rfc], total, f"Pago {fid}")

    for fid, rfc, fecha, subtotal in [f for f in facturas if f[1] == "SVP200815KL9"]:
        total = round(subtotal * 1.16, 2)
        add_txn(fecha + timedelta(days=13), clabes["SVP200815KL9"], CLABE_EMPLEADO,
               round(total * 0.85, 2), "Reembolso de gastos")

    _write_csv(salida / "bank_txns.csv",
              ["txn_id", "date", "from_clabe", "to_clabe", "amount", "reference", "channel"],
              txn_rows)

    # -- purchase_orders --------------------------------------------------
    po = 1
    po_rows: list[list] = []
    for fid, rfc, fecha, subtotal in [f for f in facturas if f[1] == "SVP200815KL9"]:
        po_rows.append([f"PO-{po:04d}", rfc, fecha.isoformat(), round(subtotal * 1.16, 2),
                       "Ricardo Elizondo Sada", "Ricardo Elizondo Sada",
                       "Asesoria estrategica trimestral"])
        po += 1
    solicitantes = [("Laura Benavides", "Jorge Salinas"), ("Marco Villalobos", "Jorge Salinas")]
    for rfc in ("CFL180312AB3", "MRN150920TU8", "TLC090114QW2"):
        for i, (fid, r2, fecha, subtotal) in enumerate([f for f in facturas if f[1] == rfc]):
            s, a = solicitantes[i % len(solicitantes)]
            po_rows.append([f"PO-{po:04d}", rfc, fecha.isoformat(), round(subtotal * 1.16, 2), s, a,
                           "Servicio recurrente"])
            po += 1
    _write_csv(salida / "purchase_orders.csv",
              ["po_id", "vendor_rfc", "date", "amount", "requester", "approver", "description"],
              po_rows)

    # -- contracts ----------------------------------------------------------
    _write_csv(salida / "contracts.csv",
              ["contract_id", "vendor_rfc", "start_date", "value", "scope_text"],
              [
                  ["CTR-0001", "CFL180312AB3", "2022-04-10", 480000.00, "Servicios fiscales anuales"],
                  ["CTR-0002", "MRN150920TU8", "2021-08-01", 720000.00, "Mantenimiento industrial anual"],
                  ["CTR-0003", "TLC090114QW2", "2020-02-15", 372000.00, "Fletes foraneos anuales"],
              ])

    # -- employees ------------------------------------------------------
    _write_csv(salida / "employees.csv",
              ["emp_id", "name", "role", "bank_clabe", "hire_date"],
              [
                  ["EMP:0007", "Ricardo Elizondo Sada", "Gerente de Compras", CLABE_EMPLEADO, "2019-03-01"],
                  ["EMP:0012", "Jorge Salinas", "Director de Operaciones", "", "2016-06-15"],
                  ["EMP:0018", "Laura Benavides", "Coordinadora de Compras", "", "2021-02-01"],
                  ["EMP:0021", "Marco Villalobos", "Coordinador de Mantenimiento", "", "2020-09-10"],
              ])

    # -- efos_list (69-B) — RFC:AAA120730823 real, "Definitivo" -----------
    _write_csv(salida / "efos_list.csv",
              ["rfc", "legal_name", "status", "publication_date"],
              [["AAA120730823", "ASESORES Y ADMINISTRADORES AGRICOLAS, S. DE R.L. DE C.V.",
               "definitivo", "2017-01-19"]])

    # -- ledger (GL) — un cargo/abono por factura, para que el importador
    #    tenga algo que subir en esa casilla tambien. No forma parte del
    #    caso sembrado; es contabilidad de rutina.
    ledger_rows = []
    entry_id = 1
    for fid, rfc, fecha, subtotal in facturas:
        total = round(subtotal * 1.16, 2)
        nombre = next(n for r, n, *_ in PROVEEDORES if r == rfc)
        ledger_rows.append([entry_id, fecha.isoformat(), "6100", "Gastos por servicios",
                            total, 0, f"Factura {fid} — {nombre}", fid, "CORP", "Jorge Salinas"])
        entry_id += 1
        ledger_rows.append([entry_id, fecha.isoformat(), "2000", "Cuentas por pagar",
                            0, total, f"Factura {fid} — {nombre}", fid, "CORP", "Jorge Salinas"])
        entry_id += 1
    _write_csv(salida / "ledger.csv",
              ["entry_id", "date", "account_code", "account_name", "debit", "credit",
               "description", "invoice_uuid", "cost_center", "approver"],
              ledger_rows)

    print(f"Escrito en: {salida}/")
    for nombre in ("vendors", "invoices", "ledger", "bank_txns", "purchase_orders",
                  "contracts", "employees", "efos_list"):
        n = sum(1 for _ in (salida / f"{nombre}.csv").open(encoding="utf-8")) - 1
        print(f"  {nombre}.csv  ({n} filas)")
    print("\nCasos sembrados a proposito:")
    print("  RFC:AAA120730823  phantom_vendor  (69-B real, sin PO ni contrato)")
    print("  RFC:SVP200815KL9  kickback        (retransfiere al aprobador de sus PO)")
    print(f"\nEn la pantalla Upload del frontend: sube cada CSV en su casilla y da 'Build estate'.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path("demo_frontend_upload"))
    args = ap.parse_args()
    construir(args.salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
