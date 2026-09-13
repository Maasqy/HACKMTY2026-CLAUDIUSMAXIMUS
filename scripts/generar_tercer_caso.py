#!/usr/bin/env python3
"""
scripts/generar_tercer_caso.py — un TERCER caso de prueba: proveedores
limpios y proveedores/clientes fraudulentos MEZCLADOS en la misma estate,
con esquemas de fraude que los dos casos anteriores no usan.

  - generar_ejemplo_frontend.py / generar_ejemplo_proveedores.py: siempre
    el mismo phantom_vendor + kickback (4 entidades).
  - generar_segundo_caso.py: threshold_splitting + round_tripping
    (3 entidades, sin proveedor fantasma ni kickback).
  - ESTE (tercer_caso): PHANTOM_VENDOR (un RFC real y distinto del 69-B,
    esta vez SI es proveedor de la empresa) + REVENUE_INFLATION (un
    esquema que ningun caso anterior habia sembrado), conviviendo con TRES
    proveedores completamente limpios y UN cliente que si paga a tiempo.
    El punto es que el Leads Log tiene que separar el trigo de la paja:
    senalar a los dos fraudulentos y dejar en paz a los limpios.

  - PHANTOM_VENDOR: RFC:AAA121206EV5 ("America Administrativa Arrollo SA
    de CV") aparece en el 69-B REAL del SAT con status 'Definitivo'
    (data/raw/Listado_completo_69-B.csv, publicado 20/11/2019). Le factura
    a la empresa con conceptos genericos y SIN una sola orden de compra ni
    contrato de respaldo -- mientras que los proveedores limpios si los
    tienen, asi que la ausencia aqui es real, no un artefacto del dataset.

  - REVENUE_INFLATION: la propia empresa (RFC:CRB170512JJ3) le factura a
    un cliente, RFC:PMX210430QW2, cerca del cierre del periodo observado
    (ventana de src.detectors.rules.detectar_ingreso_fin_periodo_sin_cobro,
    30 dias por default) y esas facturas NUNCA se cobran -- no hay
    transferencia entrante que las respalde. Un segundo cliente,
    RFC:DAL190815ZZ1, factura y cobra con normalidad en las mismas fechas:
    el contraste es el punto (no toda venta sin cobro inmediato es
    inflacion de ingresos, pero una que cae justo en el cierre y nunca se
    cobra si lo es).

Uso:
    python3 scripts/generar_tercer_caso.py              # -> tercer_caso/ (8 CSV) + tercer_caso.xlsx
    python3 scripts/generar_tercer_caso.py --salida otra/

Los CSV son para la pantalla Upload del frontend (columnas en ingles,
exactas). El .xlsx es para scripts/excel_a_estate.py (encabezados en
espanol, con alias).
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

COMPANY_RFC = "CRB170512JJ3"
COMPANY_NAME = "Comercializadora Rio Bravo SA de CV"
COMPANY_CLABE = "003180007770002222"

# rfc, razon social, clabe, giro, alta
PROVEEDORES = [
    ("MIN160305PQ2", "Materiales Industriales del Norte SA de CV", "004180002220003333", "Insumos", "2017-04-10"),
    ("TLS180920HH4", "Transportes y Logistica Sureste SA de CV", "004180002220003334", "Transporte", "2018-09-20"),
    ("SGA200114VD6", "Servicios Generales de Almacenaje SA de CV", "004180002220003335", "Almacenaje", "2020-01-14"),
    # Fantasma: RFC real del 69-B (status 'Definitivo'), SI es proveedor
    # de esta empresa -- a diferencia del segundo caso, donde el RFC del
    # 69-B aparecia en la lista pero no le facturaba a nadie.
    ("AAA121206EV5", "America Administrativa Arrollo SA de CV", "004180002220003336", "Consultoria Administrativa", "2019-05-02"),
]

# Clientes: no son proveedores, son quien le compra a la empresa. Solo
# aparecen como receiver_rfc de las facturas de ingreso de la empresa.
CLIENTE_LIMPIO = ("DAL190815ZZ1", "Distribuidora Altamira SA de CV")
CLIENTE_FRAUDE = ("PMX210430QW2", "Promotora Mercantil de la Peninsula SA de CV")

EMPLEADOS = [
    ("EMP:0201", "Laura Ibarra Cantu", "Directora de Finanzas", "", "2016-02-01"),
    ("EMP:0202", "Ruben Salcido Marin", "Gerente de Compras", "", "2018-11-12"),
    ("EMP:0203", "Diana Cepeda Roldan", "Analista de Cuentas por Cobrar", "", "2021-06-07"),
]

BASE = date(2026, 3, 2)


def _csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def construir_datos():
    """Arma las filas una sola vez; los dos formatos salen de aqui."""
    clabes = {p[0]: p[2] for p in PROVEEDORES}

    # --- facturas de COMPRA (proveedor -> empresa) ------------------------
    compras: list[tuple[str, str, date, float, str]] = []
    folio = 1

    def compra(rfc: str, dia: int, subtotal: float, concepto: str) -> None:
        nonlocal folio
        compras.append((f"A-{folio:04d}", rfc, BASE + timedelta(days=dia), subtotal, concepto))
        folio += 1

    compra("MIN160305PQ2", 5, 156000.00, "Perfil de acero y varilla, lote 88")
    compra("MIN160305PQ2", 45, 141200.00, "Lamina calibre 20, 300 piezas")
    compra("TLS180920HH4", 10, 62800.00, "Fletes Rio Bravo-Monterrey, 15 viajes")
    compra("TLS180920HH4", 50, 58300.00, "Fletes Rio Bravo-Reynosa, 13 viajes")
    compra("SGA200114VD6", 15, 47600.00, "Renta de almacen, marzo")
    compra("SGA200114VD6", 55, 47600.00, "Renta de almacen, abril")
    # Fantasma: conceptos genericos, sin PO ni contrato de respaldo (ver abajo).
    compra("AAA121206EV5", 20, 268500.00, "Servicios diversos de consultoria")
    compra("AAA121206EV5", 60, 231900.00, "Servicios varios administrativos")

    # --- facturas de INGRESO (empresa -> cliente) --------------------------
    # El cliente limpio cobra siempre; el fraudulento nunca, y sus dos
    # facturas caen justo en los ultimos 30 dias del periodo observado
    # (detectar_ingreso_fin_periodo_sin_cobro usa la fecha maxima de
    # factura de ingreso vista, nunca una fecha fija).
    ingresos: list[tuple[str, str, date, float, str]] = []
    folio_ing = 1

    def ingreso(rfc: str, dia: int, subtotal: float, concepto: str) -> None:
        nonlocal folio_ing
        ingresos.append((f"V-{folio_ing:04d}", rfc, BASE + timedelta(days=dia), subtotal, concepto))
        folio_ing += 1

    ingreso(CLIENTE_LIMPIO[0], 8, 210000.00, "Venta de mercancia, pedido 2201")
    ingreso(CLIENTE_LIMPIO[0], 38, 198500.00, "Venta de mercancia, pedido 2244")
    ingreso(CLIENTE_LIMPIO[0], 68, 225000.00, "Venta de mercancia, pedido 2290")
    ingreso(CLIENTE_FRAUDE[0], 62, 340000.00, "Venta de mercancia, pedido 2277")
    ingreso(CLIENTE_FRAUDE[0], 66, 312000.00, "Venta de mercancia, pedido 2284")

    # --- transferencias -----------------------------------------------------
    txns: list[list] = []
    n = 1

    def txn(dia: int, origen: str, destino: str, monto: float, ref: str) -> None:
        nonlocal n
        txns.append([f"B-{n:04d}", (BASE + timedelta(days=dia)).isoformat(),
                    origen, destino, round(monto, 2), ref, "SPEI"])
        n += 1

    # Pagos normales de la empresa a sus proveedores (incluye al fantasma:
    # el dinero SI sale de verdad, eso es justo lo preocupante).
    for fid, rfc, fecha, subtotal, _c in compras:
        dia = (fecha - BASE).days + 10
        txn(dia, COMPANY_CLABE, clabes[rfc], subtotal * 1.16, f"Pago {fid}")

    # Cobros del cliente limpio: siempre llega, ~6 dias despues de emitida.
    clabe_cliente_limpio = "005180009990004444"
    for fid, rfc, fecha, subtotal, _c in ingresos:
        if rfc != CLIENTE_LIMPIO[0]:
            continue
        dia = (fecha - BASE).days + 6
        txn(dia, clabe_cliente_limpio, COMPANY_CLABE, round(subtotal * 1.16, 2), f"Cobro {fid}")
    # El cliente fraudulento NUNCA paga -- por eso las dos facturas quedan
    # sin transferencia entrante que las respalde.

    # --- ordenes de compra (solo proveedores limpios) -----------------------
    pos: list[list] = []
    p = 1

    def po(rfc: str, dia: int, monto: float, solicita: str, aprueba: str, desc: str) -> None:
        nonlocal p
        pos.append([f"OC-{p:04d}", rfc, (BASE + timedelta(days=dia)).isoformat(),
                   round(monto, 2), solicita, aprueba, desc])
        p += 1

    po("MIN160305PQ2", 3, 180960.00, "Diana Cepeda Roldan", "Laura Ibarra Cantu", "Acero y varilla, lote 88")
    po("MIN160305PQ2", 44, 163792.00, "Diana Cepeda Roldan", "Laura Ibarra Cantu", "Lamina calibre 20")
    po("TLS180920HH4", 9, 72848.00, "Ruben Salcido Marin", "Laura Ibarra Cantu", "Fletes del trimestre 1")
    po("TLS180920HH4", 49, 67628.00, "Ruben Salcido Marin", "Laura Ibarra Cantu", "Fletes del trimestre 2")
    # El fantasma NO tiene una sola orden de compra: nadie la pidio.

    # --- contratos (solo proveedores limpios) --------------------------------
    contratos = [
        ["CT-0101", "MIN160305PQ2", "2017-04-10", 1850000.00, "Suministro anual de acero y varilla"],
        ["CT-0102", "TLS180920HH4", "2018-09-20", 620000.00, "Fletes foraneos, contrato marco"],
        ["CT-0103", "SGA200114VD6", "2020-01-14", 480000.00, "Renta de almacen, contrato anual"],
        # El fantasma tampoco tiene contrato: sin PO NI contrato de respaldo.
    ]

    return compras, ingresos, txns, pos, contratos, clabes


def construir(salida: Path, xlsx: Path | None) -> None:
    compras, ingresos, txns, pos, contratos, _clabes = construir_datos()

    # --- los 8 CSV para el importador del frontend -------------------------
    _csv(salida / "vendors.csv",
         ["rfc", "legal_name", "registered_date", "address", "bank_clabe", "category", "contact_email"],
         [[rfc, nombre, alta, "", clabe, giro, ""] for rfc, nombre, clabe, giro, alta in PROVEEDORES])

    filas_facturas = (
        [[fid, rfc, COMPANY_RFC, fecha.isoformat(), sub, round(sub * 0.16, 2),
          round(sub * 1.16, 2), concepto, "G03", "TRANSFERENCIA", "PUE", "vigente"]
         for fid, rfc, fecha, sub, concepto in compras]
        + [[fid, COMPANY_RFC, rfc, fecha.isoformat(), sub, round(sub * 0.16, 2),
            round(sub * 1.16, 2), concepto, "G01", "TRANSFERENCIA", "PUE", "vigente"]
           for fid, rfc, fecha, sub, concepto in ingresos]
    )
    _csv(salida / "invoices.csv",
         ["uuid", "issuer_rfc", "receiver_rfc", "issue_date", "subtotal", "iva", "total",
          "concepto_text", "uso_cfdi", "forma_pago", "metodo_pago", "status"],
         filas_facturas)

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

    # RFC real del 69-B, status 'Definitivo' -- confirmado en
    # data/raw/Listado_completo_69-B.csv (fila 5, publicacion DOF 20/11/2019).
    _csv(salida / "efos_list.csv",
         ["rfc", "legal_name", "status", "publication_date"],
         [["AAA121206EV5", "AMERICA ADMINISTRATIVA ARROLLO, S.A. DE CV.",
           "definitivo", "2019-11-20"]])

    ledger: list[list] = []
    e = 1
    for fid, rfc, fecha, sub, _c in compras:
        total = round(sub * 1.16, 2)
        nombre = next(n for r, n, *_ in PROVEEDORES if r == rfc)
        ledger.append([e, fecha.isoformat(), "5100", "Costo de ventas", total, 0,
                       f"Factura {fid} — {nombre}", fid, "PLANTA", "Laura Ibarra Cantu"])
        e += 1
        ledger.append([e, fecha.isoformat(), "2010", "Proveedores por pagar", 0, total,
                       f"Factura {fid} — {nombre}", fid, "PLANTA", "Laura Ibarra Cantu"])
        e += 1
    for fid, rfc, fecha, sub, _c in ingresos:
        total = round(sub * 1.16, 2)
        nombre = CLIENTE_LIMPIO[1] if rfc == CLIENTE_LIMPIO[0] else CLIENTE_FRAUDE[1]
        ledger.append([e, fecha.isoformat(), "1105", "Clientes por cobrar", total, 0,
                       f"Factura {fid} — {nombre}", fid, "VENTAS", "Diana Cepeda Roldan"])
        e += 1
        ledger.append([e, fecha.isoformat(), "4100", "Ingresos por ventas", 0, total,
                       f"Factura {fid} — {nombre}", fid, "VENTAS", "Diana Cepeda Roldan"])
        e += 1
    _csv(salida / "ledger.csv",
         ["entry_id", "date", "account_code", "account_name", "debit", "credit",
          "description", "invoice_uuid", "cost_center", "approver"],
         ledger)

    # --- el .xlsx para scripts/excel_a_estate.py ----------------------------
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
            for fid, rfc, fecha, sub, concepto in compras:
                ws.append([fid, rfc, COMPANY_RFC, fecha.isoformat(), sub, concepto, "PUE", "vigente"])
            for fid, rfc, fecha, sub, concepto in ingresos:
                ws.append([fid, COMPANY_RFC, rfc, fecha.isoformat(), sub, concepto, "PUE", "vigente"])

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
    print("Mezcla de limpios y fraudulentos, esquemas nuevos frente a los dos casos previos:")
    print("  RFC:AAA121206EV5  phantom_vendor      (69-B real 'Definitivo', SI es proveedor, sin PO ni contrato)")
    print("  RFC:PMX210430QW2  revenue_inflation   (2 facturas de venta al cierre del periodo, nunca cobradas)")
    print("  Limpios (no deberian aparecer en el Leads Log):")
    print("    RFC:MIN160305PQ2, RFC:TLS180920HH4, RFC:SGA200114VD6  (proveedores)")
    print("    RFC:DAL190815ZZ1  (cliente que factura y cobra con normalidad)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path("tercer_caso"))
    ap.add_argument("--xlsx", type=Path, default=Path("tercer_caso.xlsx"))
    ap.add_argument("--sin-xlsx", action="store_true")
    args = ap.parse_args()
    construir(args.salida, None if args.sin_xlsx else args.xlsx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
