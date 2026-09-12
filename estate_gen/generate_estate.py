#!/usr/bin/env python3
"""Generador del data estate para el reto Forensic Auditor (HackMTY 2026).

Produce un estate SQLite conforme a `estate_schema.sql` y una clave de
respuestas conforme a `ground_truth_schema.json`.

AISLAMIENTO DE GROUND TRUTH
---------------------------
Este archivo vive FUERA de src/. El agente y sus herramientas nunca lo
importan. La clave de respuestas se escribe en un directorio distinto al del
estate, para que una herramienta con acceso al estate no pueda alcanzarla.
Los jueces corren:  grep -r 'ground_truth' your_project/src/ --include='*.py'

Uso
---
    python3 generate_estate.py --seed 42 \
        --estate data/estates/estate_0042.db \
        --answers eval/answers/gt_0042.json

    # lote de hold-out (semillas que nadie toca durante el desarrollo)
    for s in 901 902 903 904 905; do
        python3 generate_estate.py --seed $s --schemes 4 --decoys 8 \
            --estate data/estates/holdout_$s.db --answers eval/answers/gt_$s.json
    done

Solo biblioteca estandar.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
import string
import uuid
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# CONSTANTES DE NEGOCIO
# Viven en codigo, no en prompts. Un juez puede pedir abrir este archivo.
# ---------------------------------------------------------------------------

APPROVAL_LIMIT_MXN = 50_000.00      # arriba de esto se requiere segunda firma
IVA_RATE = 0.16
PERIOD_END = date(2026, 6, 30)
PERIOD_MONTHS = 12
SCHEME_TYPES = ["phantom_vendor", "kickback", "round_tripping",
                "threshold_splitting", "revenue_inflation"]

BANK_CODES = ["002", "012", "014", "021", "030", "036", "044", "058", "072"]

CONCEPTOS_GENERICOS = [
    "Servicios de asesoria estrategica",
    "Consultoria en mejora de procesos",
    "Servicios profesionales especializados",
    "Acompanamiento tecnico y administrativo",
]
CONCEPTOS_REALES = [
    "Mantenimiento preventivo de equipo",
    "Suministro de papeleria y consumibles",
    "Transporte de carga terrestre",
    "Renta de equipo de computo",
    "Servicio de limpieza mensual",
    "Refacciones para flotilla",
    "Maniobras de mobiliario",
    "Licenciamiento de software",
]
GIROS = ["SERVICIOS", "SOLUCIONES", "GRUPO", "COMERCIALIZADORA", "CORPORATIVO",
         "DISTRIBUIDORA", "CONSTRUCTORA", "INDUSTRIAL", "LOGISTICA", "CONSULTORES"]
SUFIJOS = ["DEL NORTE", "REGIOMONTANA", "DEL VALLE", "PENINSULAR", "AZTECA",
           "MONTERREY", "INTEGRAL", "PREMIER", "GLOBAL", "ANDINA", "MERIDIANA"]
NOMBRES = ["A. Ramos", "B. Cantu", "C. Villarreal", "D. Escamilla", "E. Trevino",
           "F. Salinas", "G. Montemayor", "H. Zamora", "I. Elizondo", "J. Garza"]
CATEGORIAS = ["Consultoria", "Mantenimiento", "Logistica", "Papeleria",
              "Tecnologia", "Servicios generales", "Refacciones"]

DDL = """
CREATE TABLE vendors (
    rfc TEXT PRIMARY KEY, legal_name TEXT, registered_date TEXT, address TEXT,
    bank_clabe TEXT, category TEXT, contact_email TEXT);
CREATE TABLE invoices (
    uuid TEXT PRIMARY KEY, issuer_rfc TEXT, receiver_rfc TEXT, issue_date TEXT,
    subtotal REAL, iva REAL, total REAL, concepto_text TEXT, uso_cfdi TEXT,
    forma_pago TEXT, metodo_pago TEXT, status TEXT);
CREATE TABLE ledger (
    entry_id INTEGER PRIMARY KEY, date TEXT, account_code TEXT, account_name TEXT,
    debit REAL, credit REAL, description TEXT, invoice_uuid TEXT,
    cost_center TEXT, approver TEXT);
CREATE TABLE bank_txns (
    txn_id TEXT PRIMARY KEY, date TEXT, from_clabe TEXT, to_clabe TEXT,
    amount REAL, reference TEXT, channel TEXT);
CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY, vendor_rfc TEXT, date TEXT, amount REAL,
    requester TEXT, approver TEXT, description TEXT);
CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY, vendor_rfc TEXT, start_date TEXT,
    value REAL, scope_text TEXT);
CREATE TABLE employees (
    emp_id TEXT PRIMARY KEY, name TEXT, role TEXT, bank_clabe TEXT, hire_date TEXT);
CREATE TABLE efos_list (
    rfc TEXT PRIMARY KEY, legal_name TEXT, status TEXT, publication_date TEXT);
"""


def money(x: float) -> float:
    return round(x + 1e-9, 2)


class Estate:
    """Acumula filas y las escribe al final. Ids deterministas por semilla."""

    def __init__(self, rng: random.Random, company_rfc: str, company_clabe: str):
        self.rng = rng
        self.company_rfc = company_rfc
        self.company_clabe = company_clabe
        self.vendors: list[tuple] = []
        self.invoices: list[tuple] = []
        self.ledger: list[tuple] = []
        self.bank: list[tuple] = []
        self.pos: list[tuple] = []
        self.contracts: list[tuple] = []
        self.employees: list[tuple] = []
        self.efos: list[tuple] = []
        self._entry = 0
        self._txn = 0
        self._po = 0
        self._ctr = 0

    # -- ids ---------------------------------------------------------------
    def new_uuid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4)).upper()

    def new_txn_id(self) -> str:
        self._txn += 1
        return f"BNK-{self._txn:05d}"

    def new_po_id(self) -> str:
        self._po += 1
        return f"PO-{self._po:05d}"

    def new_contract_id(self) -> str:
        self._ctr += 1
        return f"CTR-{self._ctr:05d}"

    def clabe(self) -> str:
        return self.rng.choice(BANK_CODES) + "".join(
            self.rng.choice(string.digits) for _ in range(15))

    # -- alta de entidades -------------------------------------------------
    def add_vendor(self, rfc, name, registered, category, clabe=None, address=None):
        clabe = clabe or self.clabe()
        address = address or f"Av. {self.rng.choice(SUFIJOS).title()} {self.rng.randint(100, 4000)}, Monterrey"
        email = f"contacto@{''.join(c for c in name.lower().split(',')[0].replace(' ', ''))[:18]}.mx"
        self.vendors.append((rfc, name, registered.isoformat(), address, clabe, category, email))
        return clabe

    def add_employee(self, emp_id, name, role, hire, clabe=None):
        clabe = clabe or self.clabe()
        self.employees.append((emp_id, name, role, clabe, hire.isoformat()))
        return clabe

    def add_efos(self, rfc, name, status, publication):
        self.efos.append((rfc, name, status, publication))

    def add_contract(self, vendor_rfc, start, value, scope):
        cid = self.new_contract_id()
        self.contracts.append((cid, vendor_rfc, start.isoformat(), money(value), scope))
        return cid

    def add_po(self, vendor_rfc, when, amount, requester, approver, description):
        pid = self.new_po_id()
        self.pos.append((pid, vendor_rfc, when.isoformat(), money(amount),
                         requester, approver, description))
        return pid

    # -- documentos --------------------------------------------------------
    def add_invoice(self, issuer, receiver, when, subtotal, concepto,
                    uso="G03", forma="03", metodo="PUE", status="vigente"):
        sub = money(subtotal)
        iva = money(sub * IVA_RATE)
        total = money(sub + iva)
        u = self.new_uuid()
        self.invoices.append((u, issuer, receiver, when.isoformat(), sub, iva,
                              total, concepto, uso, forma, metodo, status))
        return u, total

    def add_ledger_pair(self, when, total, description, invoice_uuid,
                        cost_center, approver):
        self._entry += 1
        self.ledger.append((self._entry, when.isoformat(), "5000", "Gastos operativos",
                            money(total), 0.0, description, invoice_uuid,
                            cost_center, approver))
        self._entry += 1
        self.ledger.append((self._entry, when.isoformat(), "2100", "Cuentas por pagar",
                            0.0, money(total), description, invoice_uuid,
                            cost_center, approver))

    def add_txn(self, when, from_clabe, to_clabe, amount, reference, channel="SPEI"):
        tid = self.new_txn_id()
        self.bank.append((tid, when.isoformat(), from_clabe, to_clabe,
                          money(amount), reference, channel))
        return tid

    # -- escritura ---------------------------------------------------------
    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(path)
        conn.executescript(DDL)
        conn.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?,?)", self.vendors)
        conn.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", self.invoices)
        conn.executemany("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?,?,?)", self.ledger)
        conn.executemany("INSERT INTO bank_txns VALUES (?,?,?,?,?,?,?)", self.bank)
        conn.executemany("INSERT INTO purchase_orders VALUES (?,?,?,?,?,?,?)", self.pos)
        conn.executemany("INSERT INTO contracts VALUES (?,?,?,?,?)", self.contracts)
        conn.executemany("INSERT INTO employees VALUES (?,?,?,?,?)", self.employees)
        conn.executemany("INSERT INTO efos_list VALUES (?,?,?,?)", self.efos)
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def rfc_moral(rng: random.Random) -> str:
    letras = "".join(rng.choice(string.ascii_uppercase) for _ in range(3))
    anio = rng.choice(list(range(95, 100)) + list(range(0, 25)))
    return (f"{letras}{anio:02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
            + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(3)))


def company_name(rng: random.Random) -> str:
    return f"{rng.choice(GIROS)} {rng.choice(SUFIJOS)}, S.A. DE C.V."


def workday(rng: random.Random, start: date, end: date) -> date:
    span = max((end - start).days, 1)
    while True:
        d = start + timedelta(days=rng.randint(0, span))
        if d.weekday() < 5:
            return d


def load_efos(path: Path, rng: random.Random) -> dict[str, list[dict]]:
    """Lee el listado oficial 69-B del SAT. Devuelve solo definitivos y presuntos,
    que son los dos estatus que admite `efos_list.status` en el schema oficial."""
    if not path.exists():
        return {}
    with path.open(encoding="cp1252", newline="") as fh:
        rows = list(csv.reader(fh))
    head = next(i for i, r in enumerate(rows) if r and r[0].strip() == "No")
    out: dict[str, list[dict]] = {"definitivo": [], "presunto": []}

    def iso(txt: str) -> str:
        from datetime import datetime as _dt
        try:
            return _dt.strptime(txt.strip(), "%d/%m/%Y").date().isoformat()
        except ValueError:
            return ""

    for r in rows[head + 1:]:
        if len(r) < 20 or not r[1].strip():
            continue
        sit = r[3].strip().lower()
        if sit == "definitivo" and iso(r[15]):
            out["definitivo"].append({"rfc": r[1].strip(), "name": r[2].strip(),
                                      "pub": iso(r[15])})
        elif sit == "presunto" and iso(r[7]):
            out["presunto"].append({"rfc": r[1].strip(), "name": r[2].strip(),
                                    "pub": iso(r[7])})
    for v in out.values():
        rng.shuffle(v)
    return out


# ---------------------------------------------------------------------------
# Esquemas de fraude
# ---------------------------------------------------------------------------

def scheme_phantom_vendor(est, gt, rng, sid, difficulty, efos_pool, start, end):
    """Proveedor fantasma publicado en el 69-B: factura servicios que no existieron."""
    reg = efos_pool["definitivo"].pop() if efos_pool.get("definitivo") else None
    rfc = reg["rfc"] if reg else rfc_moral(rng)
    name = reg["name"] if reg else company_name(rng)
    pub = reg["pub"] if reg else (start - timedelta(days=200)).isoformat()

    alta = start + timedelta(days=rng.randint(0, 60))
    clabe = est.add_vendor(rfc, name, alta, "Consultoria")
    est.add_efos(rfc, name, "definitivo", pub)

    n = {"easy": rng.randint(6, 8), "medium": rng.randint(5, 9),
         "hard": rng.randint(3, 5)}[difficulty]
    base = {"easy": rng.uniform(250_000, 420_000),
            "medium": rng.uniform(120_000, 260_000),
            "hard": rng.uniform(60_000, 130_000)}[difficulty]

    invoices, txns, total = [], [], 0.0
    approver = rng.choice(NOMBRES)
    for _ in range(n):
        amount = base if difficulty == "easy" else base * rng.uniform(0.85, 1.15)
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, amount,
                               rng.choice(CONCEPTOS_GENERICOS), metodo="PUE")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-900 Direccion", approver)
        pay = d + timedelta(days=rng.randint(1, 12))
        tid = est.add_txn(pay, est.company_clabe, clabe, t, f"Pago factura {u[:8]}")
        invoices.append(u)
        txns.append(tid)
        total += t

    gt["schemes"].append({
        "scheme_id": sid, "type": "phantom_vendor", "entities": [f"RFC:{rfc}"],
        "supporting_invoices": invoices, "supporting_txns": txns,
        "peso_amount": money(total), "difficulty": difficulty,
        "_signals": ["vendor en efos_list definitivo", "sin contrato ni orden de compra",
                     "conceptos genericos", "alta reciente"],
    })
    return {"rfc": rfc, "clabe": clabe}


def scheme_kickback(est, gt, rng, sid, difficulty, start, end, shared_vendor=None):
    """Empleado con poder de compra dirige gasto a un proveedor que le retorna dinero."""
    emp_id = f"EMP:{rng.randint(1, 89):04d}"
    emp_name = rng.choice(NOMBRES)
    emp_clabe = est.add_employee(emp_id, emp_name, "Gerente de Compras",
                                 start - timedelta(days=rng.randint(400, 2000)))

    if shared_vendor:
        rfc, clabe = shared_vendor["rfc"], shared_vendor["clabe"]
    else:
        rfc = rfc_moral(rng)
        clabe = est.add_vendor(rfc, company_name(rng),
                               start + timedelta(days=rng.randint(0, 90)),
                               rng.choice(CATEGORIAS))

    n = rng.randint(4, 7)
    unit = {"easy": rng.uniform(180_000, 320_000),
            "medium": rng.uniform(90_000, 180_000),
            "hard": rng.uniform(55_000, 95_000)}[difficulty]

    invoices, txns, total = [], [], 0.0
    for _ in range(n):
        d = workday(rng, start, end)
        amount = unit * rng.uniform(0.9, 1.1)
        est.add_po(rfc, d - timedelta(days=rng.randint(2, 15)), money(amount * 1.16),
                   emp_name, emp_name, "Servicios contratados")   # pide y aprueba el mismo
        u, t = est.add_invoice(rfc, est.company_rfc, d, amount, rng.choice(CONCEPTOS_REALES))
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-300 Compras", emp_name)
        pay = d + timedelta(days=rng.randint(1, 10))
        tid = est.add_txn(pay, est.company_clabe, clabe, t, f"Pago factura {u[:8]}")
        invoices.append(u)
        txns.append(tid)
        total += t
        # retorno al empleado, fraccionado y con dias de retraso
        back = t * rng.uniform(0.08, 0.18)
        est.add_txn(pay + timedelta(days=rng.randint(2, 20)), clabe, emp_clabe,
                    money(back), "Transferencia")

    gt["schemes"].append({
        "scheme_id": sid, "type": "kickback", "entities": [f"RFC:{rfc}", emp_id],
        "supporting_invoices": invoices, "supporting_txns": txns,
        "peso_amount": money(total), "difficulty": difficulty,
        "_signals": ["mismo requester y approver", "precio por encima de mercado",
                     "transferencias del proveedor a la CLABE del empleado"],
    })
    return {"rfc": rfc, "clabe": clabe, "emp": emp_id}


def scheme_round_tripping(est, gt, rng, sid, difficulty, start, end, shared_vendor=None):
    """El dinero sale y regresa a la empresa tras dos o tres saltos."""
    if shared_vendor:
        rfc_a, clabe_a = shared_vendor["rfc"], shared_vendor["clabe"]
    else:
        rfc_a = rfc_moral(rng)
        clabe_a = est.add_vendor(rfc_a, company_name(rng),
                                 start - timedelta(days=rng.randint(30, 800)),
                                 rng.choice(CATEGORIAS))
    rfc_b = rfc_moral(rng)
    clabe_b = est.add_vendor(rfc_b, company_name(rng),
                             start + timedelta(days=rng.randint(0, 120)), "Servicios generales")

    hops = 2 if difficulty == "easy" else 3
    n = rng.randint(2, 4)
    invoices, txns, total = [], [], 0.0
    for _ in range(n):
        d = workday(rng, start, end - timedelta(days=40))
        amount = {"easy": rng.uniform(300_000, 600_000),
                  "medium": rng.uniform(150_000, 300_000),
                  "hard": rng.uniform(80_000, 150_000)}[difficulty]
        u, t = est.add_invoice(rfc_a, est.company_rfc, d, amount,
                               rng.choice(CONCEPTOS_GENERICOS))
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-100 Produccion",
                            rng.choice(NOMBRES))
        t1 = est.add_txn(d + timedelta(days=rng.randint(1, 6)), est.company_clabe,
                         clabe_a, t, f"Pago factura {u[:8]}")
        leak = rng.uniform(0.90, 0.97)
        mid = money(t * leak)
        t2 = est.add_txn(d + timedelta(days=rng.randint(7, 16)), clabe_a, clabe_b,
                         mid, "Pago a subcontratista")
        chain = [t1, t2]
        if hops == 3:
            rfc_c = rfc_moral(rng)
            clabe_c = est.add_vendor(rfc_c, company_name(rng),
                                     start + timedelta(days=rng.randint(0, 150)), "Logistica")
            mid2 = money(mid * rng.uniform(0.92, 0.98))
            chain.append(est.add_txn(d + timedelta(days=rng.randint(17, 24)),
                                     clabe_b, clabe_c, mid2, "Pago a subcontratista"))
            last_clabe, last_amt = clabe_c, mid2
        else:
            last_clabe, last_amt = clabe_b, mid
        chain.append(est.add_txn(d + timedelta(days=rng.randint(25, 38)), last_clabe,
                                 est.company_clabe, money(last_amt * rng.uniform(0.93, 0.99)),
                                 "Anticipo de cliente"))
        invoices.append(u)
        txns.extend(chain)
        total += t

    gt["schemes"].append({
        "scheme_id": sid, "type": "round_tripping",
        "entities": [f"RFC:{rfc_a}", f"RFC:{rfc_b}"],
        "supporting_invoices": invoices, "supporting_txns": txns,
        "peso_amount": money(total), "difficulty": difficulty,
        "_signals": [f"ciclo de {hops + 1} saltos que regresa a la CLABE de la empresa",
                     "monto se conserva casi intacto en la cadena"],
    })
    return {"rfc": rfc_a, "clabe": clabe_a}


def scheme_threshold_splitting(est, gt, rng, sid, difficulty, start, end):
    """Ordenes de compra fraccionadas justo por debajo del limite de autorizacion."""
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng),
                           start + timedelta(days=rng.randint(0, 100)),
                           rng.choice(CATEGORIAS))
    requester = rng.choice(NOMBRES)
    n = {"easy": rng.randint(10, 14), "medium": rng.randint(8, 12),
         "hard": rng.randint(5, 8)}[difficulty]
    gap = {"easy": (200, 900), "medium": (400, 2_500), "hard": (900, 4_800)}[difficulty]

    invoices, txns, total = [], [], 0.0
    window_end = start + timedelta(days=rng.randint(120, 260))
    for _ in range(n):
        d = workday(rng, start, min(window_end, end))
        amount = money(APPROVAL_LIMIT_MXN - rng.uniform(*gap))
        est.add_po(rfc, d - timedelta(days=rng.randint(1, 8)), amount,
                   requester, requester, "Compra de materiales")
        u, t = est.add_invoice(rfc, est.company_rfc, d, amount / (1 + IVA_RATE),
                               rng.choice(CONCEPTOS_REALES))
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-200 Mantenimiento",
                            requester)
        tid = est.add_txn(d + timedelta(days=rng.randint(1, 9)), est.company_clabe,
                          clabe, t, f"Pago factura {u[:8]}")
        invoices.append(u)
        txns.append(tid)
        total += t

    gt["schemes"].append({
        "scheme_id": sid, "type": "threshold_splitting", "entities": [f"RFC:{rfc}"],
        "supporting_invoices": invoices, "supporting_txns": txns,
        "peso_amount": money(total), "difficulty": difficulty,
        "_signals": [f"{n} ordenes justo por debajo de {APPROVAL_LIMIT_MXN:,.0f} MXN",
                     "mismo solicitante y aprobador", "concentradas en pocos meses"],
    })
    return {"rfc": rfc, "clabe": clabe}


def scheme_revenue_inflation(est, gt, rng, sid, difficulty, start, end):
    """Ventas simuladas a clientes relacionados al cierre del periodo, nunca cobradas."""
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng),
                           end - timedelta(days=rng.randint(20, 120)), "Cliente")
    n = rng.randint(3, 6)
    cut = end - timedelta(days=rng.randint(10, 45))

    invoices, total = [], 0.0
    for _ in range(n):
        d = workday(rng, cut, end)
        amount = {"easy": rng.uniform(400_000, 800_000),
                  "medium": rng.uniform(200_000, 400_000),
                  "hard": rng.uniform(90_000, 190_000)}[difficulty]
        # la empresa es la EMISORA: es un ingreso, no un gasto
        u, t = est.add_invoice(est.company_rfc, rfc, d, amount,
                               "Venta de producto terminado", uso="G01", metodo="PPD")
        est._entry += 1
        est.ledger.append((est._entry, d.isoformat(), "1200", "Clientes",
                           money(t), 0.0, f"Venta {u[:8]}", u, "CC-500 Ventas",
                           rng.choice(NOMBRES)))
        est._entry += 1
        est.ledger.append((est._entry, d.isoformat(), "4000", "Ingresos",
                           0.0, money(t), f"Venta {u[:8]}", u, "CC-500 Ventas",
                           rng.choice(NOMBRES)))
        invoices.append(u)
        total += t

    gt["schemes"].append({
        "scheme_id": sid, "type": "revenue_inflation", "entities": [f"RFC:{rfc}"],
        "supporting_invoices": invoices, "supporting_txns": [],
        "peso_amount": money(total), "difficulty": difficulty,
        "_signals": ["facturas de ingreso al cierre del periodo sin cobro en bank_txns",
                     "cliente dado de alta poco antes", "metodo de pago PPD sin liquidacion"],
    })
    return {"rfc": rfc, "clabe": clabe}


# ---------------------------------------------------------------------------
# Decoys: disparan un detector y estan limpios
# ---------------------------------------------------------------------------

def decoy_new_vendor_high_spend(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start + timedelta(days=rng.randint(10, 60)),
                           "Tecnologia")
    est.add_contract(rfc, start + timedelta(days=rng.randint(10, 60)), 2_400_000,
                     "Contrato marco de implementacion ERP, 18 meses, con entregables por fase")
    invs = []
    for _ in range(rng.randint(5, 9)):
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(180_000, 320_000),
                               "Implementacion ERP fase entregada")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-400 Sistemas",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 10)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "new_vendor_spend_concentration",
            "why_innocent": "Contrato marco firmado con entregables por fase y ordenes de compra que corresponden a cada factura.",
            "invoices": invs}


def decoy_round_amount_retainer(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=rng.randint(500, 1500)),
                           "Consultoria")
    est.add_contract(rfc, start - timedelta(days=400), 540_000,
                     "Iguala mensual fija de servicios contables por 45,000 MXN")
    invs = []
    for m in range(rng.randint(8, 12)):
        d = workday(rng, start + timedelta(days=30 * m), start + timedelta(days=30 * m + 5))
        if d > end:
            break
        u, t = est.add_invoice(rfc, est.company_rfc, d, 45_000.00,
                               "Iguala mensual de servicios contables")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-600 Finanzas",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 6)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "identical_round_amounts",
            "why_innocent": "Iguala mensual fija amparada por contrato vigente; el monto identico es la cuota pactada.",
            "invoices": invs}


def decoy_efos_published_after(est, gt, rng, start, end):
    """Proveedor publicado en el 69-B DESPUES de que la empresa opero con el."""
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=900),
                           rng.choice(CATEGORIAS))
    est.add_efos(rfc, "Proveedor publicado con posterioridad", "presunto",
                 (end + timedelta(days=rng.randint(60, 200))).isoformat())
    est.add_contract(rfc, start - timedelta(days=800), 300_000, "Servicio de limpieza mensual")
    invs = []
    for _ in range(rng.randint(4, 7)):
        d = workday(rng, start, start + timedelta(days=120))
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(30_000, 70_000),
                               "Servicio de limpieza mensual")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-700 Facilities",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 8)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "efos_list_match",
            "why_innocent": "La publicacion en el listado 69-B es posterior a todas las operaciones; la empresa no podia conocerla al contratar, y existe contrato con materialidad.",
            "invoices": invs}


def decoy_same_bank_as_employee(est, gt, rng, start, end):
    """El proveedor y un empleado usan el mismo banco. Coincidencia, no vinculo."""
    emp_id = f"EMP:{rng.randint(90, 99):04d}"
    bank = rng.choice(BANK_CODES)
    emp_clabe = bank + "".join(rng.choice(string.digits) for _ in range(15))
    est.add_employee(emp_id, rng.choice(NOMBRES), "Analista de Compras",
                     start - timedelta(days=rng.randint(300, 1600)), emp_clabe)
    rfc = rfc_moral(rng)
    v_clabe = bank + "".join(rng.choice(string.digits) for _ in range(15))
    est.add_vendor(rfc, company_name(rng), start - timedelta(days=600),
                   rng.choice(CATEGORIAS), clabe=v_clabe)
    est.add_contract(rfc, start - timedelta(days=550), 400_000, "Suministro de papeleria")
    invs = []
    for _ in range(rng.randint(4, 8)):
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(15_000, 60_000),
                               "Suministro de papeleria y consumibles")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-800 Administracion",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 7)), est.company_clabe, v_clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "employee_vendor_bank_linkage",
            "why_innocent": f"Comparten institucion bancaria ({bank}) pero no cuenta; no existe transferencia entre el proveedor y el empleado, y el gasto esta amparado por contrato.",
            "invoices": invs}


def decoy_refund_cycle(est, gt, rng, start, end):
    """Dinero que regresa: es una devolucion documentada, no round-tripping."""
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=700), "Refacciones")
    d = workday(rng, start, end - timedelta(days=30))
    u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(120_000, 260_000),
                           "Refacciones para flotilla")
    est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-100 Produccion",
                        rng.choice(NOMBRES))
    est.add_txn(d + timedelta(days=3), est.company_clabe, clabe, t, f"Pago factura {u[:8]}")
    est.add_txn(d + timedelta(days=rng.randint(12, 25)), clabe, est.company_clabe,
                money(t), f"Devolucion por cancelacion {u[:8]}")
    est.add_invoice(rfc, est.company_rfc, d + timedelta(days=12), -0.0 + t / (1 + IVA_RATE),
                    "Nota de credito por devolucion", status="cancelado")
    return {"entity": f"RFC:{rfc}", "signal": "circular_payment_flow",
            "why_innocent": "El retorno es una devolucion por cancelacion, amparada por nota de credito por el mismo importe.",
            "invoices": [u]}


def decoy_below_threshold_recurring(est, gt, rng, start, end):
    """Compras recurrentes por debajo del umbral: es el precio del servicio, no fraccionamiento."""
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=1100), "Logistica")
    est.add_contract(rfc, start - timedelta(days=1000), 560_000,
                     "Tarifa unitaria por viaje de transporte, 48,000 MXN por ruta")
    invs = []
    for _ in range(rng.randint(8, 12)):
        d = workday(rng, start, end)
        amount = money(48_000 * rng.uniform(0.97, 1.03))
        est.add_po(rfc, d - timedelta(days=2), amount, rng.choice(NOMBRES),
                   rng.choice(NOMBRES), "Viaje de transporte segun tarifa contratada")
        u, t = est.add_invoice(rfc, est.company_rfc, d, amount / (1 + IVA_RATE),
                               "Transporte de carga terrestre")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-100 Produccion",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 8)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "below_approval_threshold_pattern",
            "why_innocent": "La tarifa unitaria por viaje esta fijada en contrato; los montos quedan bajo el umbral por precio, no por fraccionamiento, y el solicitante y el aprobador son distintos.",
            "invoices": invs}


def decoy_generic_concept(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=1400), "Consultoria")
    est.add_contract(rfc, start - timedelta(days=1300), 900_000,
                     "Consultoria fiscal con entregables trimestrales")
    invs = []
    for _ in range(rng.randint(3, 6)):
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(70_000, 140_000),
                               rng.choice(CONCEPTOS_GENERICOS))
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-600 Finanzas",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 9)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "generic_service_concept",
            "why_innocent": "Concepto generico pero con contrato de consultoria fiscal vigente desde hace mas de tres anos y entregables trimestrales.",
            "invoices": invs}


def decoy_cash_channel(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=900),
                           "Servicios generales")
    invs = []
    for _ in range(rng.randint(6, 10)):
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(2_000, 9_000),
                               "Servicio de limpieza mensual", forma="01")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-700 Facilities",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(0, 4)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}", channel="efectivo")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "cash_channel_payments",
            "why_innocent": "Pagos en efectivo de bajo monto a proveedor con tres anos de historial; cada uno tiene CFDI y registro contable correspondiente.",
            "invoices": invs}


def decoy_missing_po(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=200),
                           rng.choice(CATEGORIAS))
    invs = []
    for _ in range(rng.randint(1, 3)):
        d = workday(rng, start, end)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(8_000, 28_000),
                               "Compra unica de mobiliario")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-800 Administracion",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 6)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "purchase_without_po",
            "why_innocent": "Compra unica de monto menor, por debajo del umbral que exige orden de compra; existe factura y registro contable.",
            "invoices": invs}


def decoy_weekend_entries(est, gt, rng, start, end):
    rfc = rfc_moral(rng)
    clabe = est.add_vendor(rfc, company_name(rng), start - timedelta(days=1800), "Mantenimiento")
    est.add_contract(rfc, start - timedelta(days=1700), 700_000,
                     "Mantenimiento correctivo con guardias de fin de semana")
    invs = []
    for _ in range(rng.randint(4, 7)):
        d = start + timedelta(days=rng.randint(0, (end - start).days))
        while d.weekday() < 5:
            d += timedelta(days=1)
        u, t = est.add_invoice(rfc, est.company_rfc, d, rng.uniform(20_000, 65_000),
                               "Mantenimiento correctivo en guardia")
        est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u, "CC-200 Mantenimiento",
                            rng.choice(NOMBRES))
        est.add_txn(d + timedelta(days=rng.randint(1, 7)), est.company_clabe, clabe, t,
                    f"Pago factura {u[:8]}")
        invs.append(u)
    return {"entity": f"RFC:{rfc}", "signal": "weekend_transaction_timing",
            "why_innocent": "El contrato incluye guardias de fin de semana; las fechas corresponden a intervenciones programadas fuera de horario.",
            "invoices": invs}


DECOYS = [decoy_new_vendor_high_spend, decoy_round_amount_retainer,
          decoy_efos_published_after, decoy_same_bank_as_employee,
          decoy_refund_cycle, decoy_below_threshold_recurring,
          decoy_generic_concept, decoy_cash_channel,
          decoy_missing_po, decoy_weekend_entries]


# ---------------------------------------------------------------------------
# Ruido legitimo
# ---------------------------------------------------------------------------

def add_background(est, rng, n_vendors, start, end):
    for _ in range(n_vendors):
        rfc = rfc_moral(rng)
        alta = start - timedelta(days=rng.randint(200, 3600))
        clabe = est.add_vendor(rfc, company_name(rng), alta, rng.choice(CATEGORIAS))
        if rng.random() < 0.6:
            est.add_contract(rfc, alta + timedelta(days=rng.randint(0, 200)),
                             rng.uniform(200_000, 2_000_000), "Contrato de suministro")
        for _ in range(rng.randint(3, 12)):
            d = workday(rng, start, end)
            amount = rng.uniform(3_000, 190_000)
            requester, approver = rng.sample(NOMBRES, 2)
            if amount * 1.16 > APPROVAL_LIMIT_MXN:
                est.add_po(rfc, d - timedelta(days=rng.randint(1, 12)),
                           money(amount * 1.16), requester, approver, "Compra operativa")
            u, t = est.add_invoice(rfc, est.company_rfc, d, amount,
                                   rng.choice(CONCEPTOS_REALES))
            est.add_ledger_pair(d, t, f"Registro factura {u[:8]}", u,
                                rng.choice(["CC-100 Produccion", "CC-200 Mantenimiento",
                                            "CC-800 Administracion"]), approver)
            est.add_txn(d + timedelta(days=rng.randint(1, 14)), est.company_clabe,
                        clabe, t, f"Pago factura {u[:8]}")
    for i in range(1, rng.randint(8, 14)):
        est.add_employee(f"EMP:{i:04d}", rng.choice(NOMBRES),
                         rng.choice(["Analista de Compras", "Gerente de Planta",
                                     "Contador General", "Jefe de Mantenimiento"]),
                         start - timedelta(days=rng.randint(200, 3000)))


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

def build(seed: int, n_schemes: int, n_decoys: int, difficulty: str,
          entangle: bool, n_vendors: int, efos_path: Path):
    rng = random.Random(seed)
    end = PERIOD_END
    start = end - timedelta(days=30 * PERIOD_MONTHS)

    company_rfc = rfc_moral(rng)
    est = Estate(rng, company_rfc, "".join(["646"] + [rng.choice(string.digits)
                                                      for _ in range(15)]))
    gt: dict = {"seed": seed, "company_rfc": company_rfc, "schemes": [], "decoys": []}

    efos_pool = load_efos(efos_path, rng)
    add_background(est, rng, n_vendors, start, end)

    chosen = SCHEME_TYPES[:] if n_schemes >= len(SCHEME_TYPES) else rng.sample(SCHEME_TYPES, n_schemes)
    rng.shuffle(chosen)
    if entangle and "phantom_vendor" in chosen:
        chosen.remove("phantom_vendor")
        chosen.insert(0, "phantom_vendor")

    shared = None
    for i, kind in enumerate(chosen, start=1):
        sid = f"S{i}_{kind}"
        diff = difficulty if difficulty != "mixed" else rng.choice(["easy", "medium", "hard"])
        if kind == "phantom_vendor":
            shared = scheme_phantom_vendor(est, gt, rng, sid, diff, efos_pool, start, end)
        elif kind == "kickback":
            link = shared if entangle and shared else None
            scheme_kickback(est, gt, rng, sid, diff, start, end, shared_vendor=link)
            if link:
                shared = None
        elif kind == "round_tripping":
            link = shared if entangle and shared else None
            scheme_round_tripping(est, gt, rng, sid, diff, start, end, shared_vendor=link)
            if link:
                shared = None
        elif kind == "threshold_splitting":
            scheme_threshold_splitting(est, gt, rng, sid, diff, start, end)
        elif kind == "revenue_inflation":
            scheme_revenue_inflation(est, gt, rng, sid, diff, start, end)

    for fn in rng.sample(DECOYS, min(n_decoys, len(DECOYS))):
        gt["decoys"].append(fn(est, gt, rng, start, end))

    return est, gt


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un data estate conforme a estate_schema.sql")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--schemes", type=int, default=3, choices=range(0, 6))
    ap.add_argument("--decoys", type=int, default=6, choices=range(0, 11))
    ap.add_argument("--difficulty", default="mixed",
                    choices=["easy", "medium", "hard", "mixed"])
    ap.add_argument("--entangle", action="store_true",
                    help="Comparte una entidad entre dos esquemas")
    ap.add_argument("--vendors", type=int, default=40, help="proveedores de fondo, limpios")
    ap.add_argument("--efos-list", type=Path, default=Path("data/raw/Listado_completo_69-B.csv"))
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--answers", type=Path, required=True)
    args = ap.parse_args()

    if args.answers.resolve().parent == args.estate.resolve().parent:
        raise SystemExit("ERROR: la clave de respuestas no puede vivir junto al estate. "
                         "Usa directorios distintos (p. ej. data/estates/ y eval/answers/).")

    est, gt = build(args.seed, args.schemes, args.decoys, args.difficulty,
                    args.entangle, args.vendors, args.efos_list)
    est.write(args.estate)
    args.answers.parent.mkdir(parents=True, exist_ok=True)
    args.answers.write_text(json.dumps(gt, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(s["peso_amount"] for s in gt["schemes"])
    print(f"estate  : {args.estate}")
    print(f"answers : {args.answers}")
    print(f"  vendors {len(est.vendors)}  invoices {len(est.invoices)}  "
          f"ledger {len(est.ledger)}  bank_txns {len(est.bank)}  "
          f"POs {len(est.pos)}  contracts {len(est.contracts)}  "
          f"employees {len(est.employees)}  efos {len(est.efos)}")
    print(f"  esquemas: {len(gt['schemes'])}   decoys: {len(gt['decoys'])}")
    for s in gt["schemes"]:
        print(f"    {s['scheme_id']:<28} {s['difficulty']:<7} "
              f"{s['peso_amount']:>14,.2f} MXN  {', '.join(s['entities'])}")
    print(f"  exposicion total: {total:,.2f} MXN")


if __name__ == "__main__":
    main()
