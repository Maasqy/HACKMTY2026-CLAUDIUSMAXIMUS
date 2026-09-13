#!/usr/bin/env python3
"""
generate_estate.py — HACKMTY2026 Forensic Auditor track.

Builds a synthetic Mexican "data estate" (8 relational tables, CFDI 4.0 /
Anexo 20 field names) plus its answer key, from two real ingredients:

  1. The SAT Articulo 69-B list (Listado_completo_69-B.csv) — real RFCs of
     companies the tax authority has published as EFOS (issuers of invoices
     for operations that likely never happened). Used to populate efos_list
     and to cast the phantom_vendor scheme with a real, publicly-listed RFC.

  2. IBM AMLSim's bundled sample output (AMLSim/sample/20K_cycle200.tgz) —
     a transaction graph with labelled laundering cycles. The actual
     transferred amounts and the actual cycle topology (which fraud-flagged
     account sends to which, in what order) are pulled out of that graph and
     re-skinned as CLABE-to-CLABE SPEI transfers between Mexican entities,
     instead of being invented from scratch.

Everything else (vendors, employees, contracts, invoices, ledger, background
noise, decoys) is generated deterministically from --seed.

This script lives in estate_gen/, outside src/ — the agent under investigation
never imports anything from this file or its directory.

Outputs:
  data/estates/estate_NNNN.db   SQLite, schema = student-materials/forensic-auditor/estate_schema.sql
  eval/answers/gt_NNNN.json     ground truth, schema = student-materials/forensic-auditor/ground_truth_schema.json

gt_NNNN.json is the answer key. Per the track rules it must never be read by
the agent under investigation, its tools, or anything they import — only by
your own evaluation harness (eval/harness.py). Keep it out of the agent's
import path. Judges may run: grep -r 'ground_truth' src/ --include='*.py'

Usage:
  python3 estate_gen/generate_estate.py --seed 42
  python3 estate_gen/generate_estate.py --seed 7
  python3 estate_gen/generate_estate.py --seed 3 --db-dir custom/db --gt-dir custom/gt
"""

import argparse
import csv
import io
import json
import random
import re
import sqlite3
import sys
import tarfile
import uuid
from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# Paths. This file lives in <repo>/estate_gen/, so REPO_ROOT is its parent.
# --------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_SAT_CSV = REPO_ROOT / "Listado_completo_69-B.csv"
DEFAULT_AMLSIM_TGZ = REPO_ROOT / "AMLSim" / "sample" / "20K_cycle200.tgz"
DEFAULT_DB_DIR = REPO_ROOT / "data" / "estates"
DEFAULT_GT_DIR = REPO_ROOT / "eval" / "answers"

# --------------------------------------------------------------------------
# CFDI 4.0 / Anexo 20 catalog codes (SAT public catalogs, factual reference
# data — not text lifted from the guide document).
# --------------------------------------------------------------------------

USO_CFDI = ["G01", "G02", "G03", "I01", "P01", "D01", "S01", "CP01"]
FORMA_PAGO = ["01", "02", "03", "04", "28", "99"]
METODO_PAGO = ["PUE", "PPD"]
CHANNELS = ["SPEI", "cheque", "efectivo"]
IVA_RATE = 0.16

CATEGORIES = [
    "Consultoria", "Mantenimiento", "Logistica", "Publicidad", "Tecnologia",
    "Construccion", "Papeleria", "Limpieza", "Seguridad", "Transporte",
]
ROLES = [
    "Gerente de Compras", "Analista de Cuentas por Pagar", "Contralor",
    "Director de Operaciones", "Auxiliar Contable", "Gerente de Planta",
    "Comprador Senior", "Tesorero",
]

RFC_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
RFC_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MORAL_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{2,3}$")


def rng_choice_weighted_date(rng, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, max(span, 0)))


# --------------------------------------------------------------------------
# Shared distributions for amounts and registered_date.
#
# Earlier versions of this generator gave fraud its own amount scale and its
# own registration-date window, disjoint from the honest population. That
# made a downstream classifier trained on these estates hit ~100% accuracy
# with a single feature (tiene_contrato, or dias_antiguedad_al_facturar) —
# not because the model is good, but because the data made fraud and honest
# populations trivially separable by construction. Every vendor — fraud,
# decoy, or background — now draws its amounts and its registration date
# from the SAME distributions below. What distinguishes fraud is the
# *pattern* (missing paperwork, a cycle that closes, a threshold cluster,
# a kickback transfer, unpaid period-end revenue), not a different number
# range or a different date range.
# --------------------------------------------------------------------------

BAND_SERVICIO_RECURRENTE = (15000.0, 150000.0)
BAND_REVENUE = (50000.0, 320000.0)
# round_tripping's cycle amounts must land inside a band that overlaps every
# other invoice type's amounts, or monto_promedio_factura becomes a perfect,
# single-feature separator for this scheme on its own (see
# cycle_pesos_in_range's docstring). Deliberately wide/overlapping with both
# bands above, not a new disjoint magnitude.
BAND_ROUND_TRIPPING = (20000.0, 200000.0)


# Concepto (free-text line description) wording. A vague CFDI concepto is a
# real audit signal, but it is NOT exclusive to fraud: plenty of legitimate
# invoices say "servicios diversos" because whoever captured them was lazy,
# not because the service didn't exist. Before this, every honest invoice
# used specific wording and phantom_vendor/threshold_splitting used generic
# wording 100% of the time, which made pct_concepto_generico a perfect
# single-feature separator (see SOBRE_EL_MODELO.md). Both sides now draw
# from the SAME two template pools, with different probabilities — the
# signal survives as evidence, it just stops being proof on its own.
GENERIC_CONCEPT_TEMPLATES = (
    "{cat} - conceptos varios del periodo",
    "{cat} - servicios diversos",
    "Servicios generales de {cat_lower}",
    "{cat} - varias partidas del mes",
    "Suministros diversos",
)
SPECIFIC_CONCEPT_TEMPLATES = (
    "{cat} - servicios del periodo",
    "{cat} segun contrato vigente",
    "{cat} - entregable mensual documentado",
    "{cat} - orden de servicio con acta de entrega",
)


def concepto_texto(rng: random.Random, category: str, generic_prob: float) -> str:
    """One shared concepto-text distribution. `generic_prob` is the only
    thing that differs between an honest vendor and a scheme."""
    pool = GENERIC_CONCEPT_TEMPLATES if rng.random() < generic_prob else SPECIFIC_CONCEPT_TEMPLATES
    return rng.choice(pool).format(cat=category, cat_lower=category.lower())


# How often each kind of vendor produces vague wording. Honest is NOT zero
# and fraud is NOT one — that overlap is the whole point.
GENERIC_PROB_HONESTO = 0.25
GENERIC_PROB_ESQUEMA = 0.80


def draw_amount(rng: random.Random, aml: "AMLSimSeed", low: float, high: float,
                 use_aml_prob: float = 0.5) -> float:
    """One shared amount distribution for the whole estate. About half the
    time the number is a real AMLSim transaction amount rescaled into
    [low, high]; the rest of the time it's drawn uniformly from the same
    band. Fraud and honest invoices call this with the SAME (low, high) —
    the amount itself carries no fraud signal, only the surrounding pattern
    does."""
    if rng.random() < use_aml_prob:
        return aml.amounts_in_range(rng, 1, low, high)[0]
    return round(rng.uniform(low, high), 2)


def draw_registered_date(rng: random.Random, period_start: date, recent_prob: float) -> str:
    """One shared registration-date distribution. `recent_prob` biases how
    often the draw lands in a 'recently registered' window (1-9 months
    before period_start) versus an 'established vendor' window (1-7 years
    before). Fraud uses a higher recent_prob (recency is a real, if noisy,
    fraud signal) and honest vendors a lower one — but both windows
    overlap the same calendar range, so no fixed date cutoff perfectly
    separates the two classes the way disjoint hardcoded ranges did."""
    if rng.random() < recent_prob:
        start = period_start - timedelta(days=270)
        end = period_start - timedelta(days=30)
    else:
        start = period_start - timedelta(days=365 * 7)
        end = period_start - timedelta(days=365)
    return rng_choice_weighted_date(rng, start, end).isoformat()


def make_rfc(rng: random.Random, persona_moral: bool = True) -> str:
    n_letters = 3 if persona_moral else 4
    letters = "".join(rng.choice(RFC_LETTERS) for _ in range(n_letters))
    yy = rng.randint(0, 26)
    mm = rng.randint(1, 12)
    dd = rng.randint(1, 28)
    datepart = f"{yy:02d}{mm:02d}{dd:02d}"
    homoclave = "".join(rng.choice(RFC_ALNUM) for _ in range(3))
    return f"{letters}{datepart}{homoclave}"


def make_clabe(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789") for _ in range(18))


def new_uuid(rng: random.Random) -> str:
    # Deterministic given the seeded rng (not the stdlib uuid4, which is
    # not reproducible across runs).
    return str(uuid.UUID(int=rng.getrandbits(128))).upper()


# --------------------------------------------------------------------------
# Ingredient 1: SAT Articulo 69-B list
# --------------------------------------------------------------------------

def load_sat_69b(csv_path: Path):
    """Return a list of dicts: rfc, legal_name, status, publication_date."""
    rows = []
    with open(csv_path, encoding="latin-1", newline="") as f:
        reader = list(csv.reader(f))

    header_idx = None
    for i, row in enumerate(reader):
        if row and row[0].strip() == "No":
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError(f"Could not find the header row in {csv_path}")

    for row in reader[header_idx + 1:]:
        if len(row) < 4:
            continue
        rfc = row[1].strip().upper()
        legal_name = row[2].strip()
        situacion = row[3].strip()
        if not rfc or not MORAL_RFC_RE.match(rfc):
            continue
        situacion_norm = situacion.lower()
        # Four real, distinct SAT categories (Situacion del Contribuyente),
        # not two buckets. Definitivo = confirmed EFOS (shell company).
        # Presunto = presumed, not yet resolved. Desvirtuado and Sentencia
        # Favorable are BOTH real "cleared" outcomes (the taxpayer rebutted
        # the presumption administratively, or won in court) — genuine,
        # government-confirmed non-fraud examples, not synthetic decoys.
        if "definitivo" in situacion_norm:
            status = "definitivo"
        elif "presunto" in situacion_norm:
            status = "presunto"
        elif "desvirtuado" in situacion_norm:
            status = "desvirtuado"
        elif "favorable" in situacion_norm:
            status = "favorable"
        else:
            status = "otro"
        rows.append({"rfc": rfc, "legal_name": legal_name or f"Contribuyente {rfc}",
                      "status": situacion, "status_norm": status})
    return rows


# --------------------------------------------------------------------------
# Ingredient 2: AMLSim sample output — real transferred amounts and a real
# laundering cycle's topology, pulled straight out of the simulator's graph.
# --------------------------------------------------------------------------

class AMLSimSeed:
    """Loads AMLSim's bundled 20K_cycle200 sample and exposes:
      - a pool of real transaction amounts from fraud-flagged accounts
      - one real cycle (sequence of fraud account ids that transact in a
        loop) discovered by walking the actual edge list
    """

    def __init__(self, tgz_path: Path):
        self.fraud_amounts = []
        self.cycle_amounts = []
        self._load(tgz_path)

    def _load(self, tgz_path: Path):
        with tarfile.open(tgz_path, "r:gz") as tar:
            nodes_member = next(m for m in tar.getmembers() if m.name.endswith("nodes.csv"))
            tx_member = next(m for m in tar.getmembers() if m.name.endswith("transactions.csv"))

            nodes_text = tar.extractfile(nodes_member).read().decode("utf-8")
            tx_text = tar.extractfile(tx_member).read().decode("utf-8")

        fraud_nodes = set()
        for row in csv.DictReader(io.StringIO(nodes_text)):
            if row.get("isFraud") in ("1", "true", "True"):
                fraud_nodes.add(row["nodeid"])

        adjacency = {}
        edge_amount = {}
        for row in csv.DictReader(io.StringIO(tx_text)):
            src, dst, val = row["sourceNodeId"], row["targetNodeId"], float(row["value"])
            if src in fraud_nodes and dst in fraud_nodes:
                adjacency.setdefault(src, []).append(dst)
                edge_amount[(src, dst)] = val
                self.fraud_amounts.append(val)

        # Walk the real edge list looking for one actual short cycle
        # (a laundering account that eventually pays back to itself).
        cycle_path = self._find_cycle(adjacency, max_depth=4, budget=20000)
        if cycle_path:
            self.cycle_amounts = [edge_amount[(a, b)] for a, b in zip(cycle_path, cycle_path[1:])]
        if not self.fraud_amounts:
            self.fraud_amounts = [125.0, 150.0, 175.0, 200.0]
        if not self.cycle_amounts:
            self.cycle_amounts = self.fraud_amounts[:3] or [150.0, 160.0, 155.0]

    @staticmethod
    def _find_cycle(adjacency, max_depth, budget):
        visited_budget = [0]

        def dfs(start, node, path, depth):
            visited_budget[0] += 1
            if visited_budget[0] > budget:
                return None
            if depth > max_depth:
                return None
            for nxt in adjacency.get(node, []):
                if nxt == start and depth >= 2:
                    return path + [nxt]
                if nxt in path:
                    continue
                found = dfs(start, nxt, path + [nxt], depth + 1)
                if found:
                    return found
            return None

        for start in list(adjacency.keys())[:500]:
            result = dfs(start, start, [start], 1)
            if result:
                return result
        return None

    def amounts(self, rng: random.Random, n: int, scale: float):
        pool = self.fraud_amounts
        return [round(rng.choice(pool) * scale, 2) for _ in range(n)]

    def amounts_in_range(self, rng: random.Random, n: int, low: float, high: float):
        """Real AMLSim transaction amounts, min-max normalized into
        [low, high]. Unlike `amounts()` (which just multiplies by an
        arbitrary scale — the thing that used to give every scheme its own
        disjoint magnitude band), this always lands in the SAME band you
        hand it, so the same call can be reused for fraud and for honest
        background invoices without the amount itself becoming a tell."""
        pool = self.fraud_amounts
        pmin, pmax = min(pool), max(pool)
        span = (pmax - pmin) or 1.0
        out = []
        for _ in range(n):
            v = rng.choice(pool)
            norm = (v - pmin) / span
            out.append(round(low + norm * (high - low), 2))
        return out

    def cycle_pesos(self, scale: float):
        return [round(v * scale, 2) for v in self.cycle_amounts]

    def cycle_pesos_in_range(self, rng: random.Random, n: int, low: float, high: float) -> list[float]:
        """`n` chained amounts, each close to the last (a small per-hop
        decay/variation, like fees skimmed at each layering step), anchored
        by a real AMLSim amount rescaled into [low, high] via
        amounts_in_range — the SAME shared band and the SAME real-amount
        pool every other invoice type draws from.

        This replaces an earlier version that band-normalized
        self.cycle_amounts directly: that list is only ever [334.92, 165.16,
        18.23] (AMLSimSeed's cycle discovery isn't reseeded per estate — it
        walks the same fixed sample every time), so an affine transform of
        it produced the literal SAME three output pesos in every one of the
        200 estates. monto_promedio_factura for round_tripping's one
        invoice was then a constant, making it a perfect, zero-overlap
        separator for this scheme in the ML model (see SOBRE_EL_MODELO.md).
        Anchoring on an `amounts_in_range` draw instead makes this vary
        per-estate like everything else, while keeping the 'amount roughly
        conserved through the chain' pattern round_tripping is actually
        about."""
        anchor = self.amounts_in_range(rng, 1, low, high)[0]
        out = [anchor]
        for _ in range(n - 1):
            anchor = round(anchor * rng.uniform(0.85, 1.05), 2)
            out.append(anchor)
        return out


# --------------------------------------------------------------------------
# Estate builder
# --------------------------------------------------------------------------

SCHEMA_SQL = (REPO_ROOT / "student-materials" / "forensic-auditor" / "estate_schema.sql")


class Estate:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.vendors = []          # dict rows
        self.employees = []
        self.contracts = []
        self.purchase_orders = []
        self.invoices = []
        self.ledger = []
        self.bank_txns = []
        self.efos_list = []
        self._entry_id = 1
        self._period_start = date(2026, 1, 1)
        self._period_end = date(2026, 8, 31)

    # -- id helpers ---------------------------------------------------

    def next_entry_id(self):
        v = self._entry_id
        self._entry_id += 1
        return v

    def rand_date(self):
        return rng_choice_weighted_date(self.rng, self._period_start, self._period_end).isoformat()

    # -- population -----------------------------------------------------

    def add_vendor(self, rfc, legal_name, registered_date, category=None):
        v = {
            "rfc": rfc,
            "legal_name": legal_name,
            "registered_date": registered_date,
            "address": f"{self.rng.choice(['Calle', 'Av.'])} {self.rng.randint(1,999)}, "
                       f"{self.rng.choice(['Monterrey','San Pedro','Apodaca','Guadalupe','Santa Catarina'])}, NL",
            "bank_clabe": make_clabe(self.rng),
            "category": category or self.rng.choice(CATEGORIES),
            "contact_email": f"contacto@{re.sub('[^a-z]', '', legal_name.lower())[:12] or 'proveedor'}.mx",
        }
        self.vendors.append(v)
        return v

    def add_employee(self, name, role, hire_date):
        emp_id = f"EMP:{len(self.employees) + 1:04d}"
        e = {
            "emp_id": emp_id, "name": name, "role": role,
            "bank_clabe": make_clabe(self.rng), "hire_date": hire_date,
        }
        self.employees.append(e)
        return e

    def add_contract(self, vendor_rfc, start_date, value, scope_text):
        c = {
            "contract_id": f"CTR-{len(self.contracts) + 1:05d}",
            "vendor_rfc": vendor_rfc, "start_date": start_date,
            "value": round(value, 2), "scope_text": scope_text,
        }
        self.contracts.append(c)
        return c

    def add_po(self, vendor_rfc, dt, amount, requester, approver, description):
        po = {
            "po_id": f"PO-{len(self.purchase_orders) + 1:05d}",
            "vendor_rfc": vendor_rfc, "date": dt, "amount": round(amount, 2),
            "requester": requester, "approver": approver, "description": description,
        }
        self.purchase_orders.append(po)
        return po

    def add_invoice(self, issuer_rfc, receiver_rfc, issue_date, subtotal,
                     concepto_text, uso_cfdi=None, forma_pago=None,
                     metodo_pago=None, status="vigente", uuid_override=None):
        subtotal = round(subtotal, 2)
        iva = round(subtotal * IVA_RATE, 2)
        total = round(subtotal + iva, 2)
        inv = {
            "uuid": uuid_override or new_uuid(self.rng),
            "issuer_rfc": issuer_rfc, "receiver_rfc": receiver_rfc,
            "issue_date": issue_date, "subtotal": subtotal, "iva": iva, "total": total,
            "concepto_text": concepto_text,
            "uso_cfdi": uso_cfdi or self.rng.choice(USO_CFDI),
            "forma_pago": forma_pago or self.rng.choice(FORMA_PAGO),
            "metodo_pago": metodo_pago or self.rng.choice(METODO_PAGO),
            "status": status,
        }
        self.invoices.append(inv)
        return inv

    def add_ledger_pair(self, dt, expense_account, expense_name, amount,
                         description, invoice_uuid, cost_center, approver,
                         is_revenue=False):
        if is_revenue:
            debit_acc, debit_name = "1100", "Bancos"
            credit_acc, credit_name = expense_account, expense_name
        else:
            debit_acc, debit_name = expense_account, expense_name
            credit_acc, credit_name = "2100", "Cuentas por pagar"
        e1 = {"entry_id": self.next_entry_id(), "date": dt, "account_code": debit_acc,
              "account_name": debit_name, "debit": round(amount, 2), "credit": 0.0,
              "description": description, "invoice_uuid": invoice_uuid,
              "cost_center": cost_center, "approver": approver}
        e2 = {"entry_id": self.next_entry_id(), "date": dt, "account_code": credit_acc,
              "account_name": credit_name, "debit": 0.0, "credit": round(amount, 2),
              "description": description, "invoice_uuid": invoice_uuid,
              "cost_center": cost_center, "approver": approver}
        self.ledger.append(e1)
        self.ledger.append(e2)
        return e1, e2

    def add_bank_txn(self, dt, from_clabe, to_clabe, amount, reference, channel=None):
        txn = {
            "txn_id": f"BNK-{len(self.bank_txns) + 1:05d}",
            "date": dt, "from_clabe": from_clabe, "to_clabe": to_clabe,
            "amount": round(amount, 2), "reference": reference,
            "channel": channel or self.rng.choice(CHANNELS),
        }
        self.bank_txns.append(txn)
        return txn

    # -- write out --------------------------------------------------

    def to_sqlite(self, db_path: Path):
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL.read_text())

        def insert_many(table, rows):
            if not rows:
                return
            cols = list(rows[0].keys())
            placeholders = ",".join("?" for _ in cols)
            sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
            conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

        insert_many("vendors", self.vendors)
        insert_many("employees", self.employees)
        insert_many("contracts", self.contracts)
        insert_many("purchase_orders", self.purchase_orders)
        insert_many("invoices", self.invoices)
        insert_many("ledger", self.ledger)
        insert_many("bank_txns", self.bank_txns)
        insert_many("efos_list", self.efos_list)
        conn.commit()
        conn.close()


# --------------------------------------------------------------------------
# Scenario generation
# --------------------------------------------------------------------------

COMPANY_APPROVERS = ["L. Garza", "M. Trevino", "R. Sada", "A. Elizondo", "C. Villarreal"]
CLIENT_NAME_POOL = [
    "Distribuidora del Norte SA de CV", "Comercializadora Regia SC",
    "Grupo Industrial Cumbres SA de CV", "Servicios Metropolitanos SA de CV",
    "Innovacion y Desarrollo del Bajio SA de CV",
]
VENDOR_NAME_POOL = [
    "Soluciones Integrales Regiomontanas SA de CV", "Servicios Corporativos Alfa SC",
    "Grupo Logistico del Norte SA de CV", "Mantenimiento Industrial Vega SA de CV",
    "Consultoria Estrategica Cumbres SC", "Papeleria y Suministros Elizondo SA de CV",
    "Transportes y Fletes San Nicolas SA de CV", "Seguridad Privada Sierra Madre SA de CV",
    "Publicidad y Medios Sultana SA de CV", "Construcciones Treviño Hnos SA de CV",
    "Limpieza Profesional Apodaca SA de CV", "Tecnologia Aplicada Garza SA de CV",
]
EMPLOYEE_NAME_POOL = [
    "Ana Sofia Ramirez", "Jose Luis Gonzalez", "Maria Fernanda Cantu",
    "Carlos Alberto Salinas", "Diana Patricia Longoria", "Eduardo Villareal",
    "Gabriela Montemayor", "Hector Ivan Farias", "Iris Ochoa", "Javier Benavides",
    "Karla Rodriguez", "Luis Fernando Barragan",
]


def build_background(estate: Estate, sat_pool, aml: "AMLSimSeed"):
    rng = estate.rng

    # A modest slice of the real 69-B list for the efos_list table itself.
    definitivos = [r for r in sat_pool if r["status_norm"] == "definitivo"]
    presuntos = [r for r in sat_pool if r["status_norm"] == "presunto"]
    sample_pool = rng.sample(definitivos, min(120, len(definitivos))) + \
        rng.sample(presuntos, min(30, len(presuntos)))
    for r in sample_pool:
        estate.efos_list.append({
            "rfc": r["rfc"], "legal_name": r["legal_name"],
            "status": r["status_norm"],
            "publication_date": estate.rand_date(),
        })

    # Normal (honest) vendor pool. recent_prob=0.20: mostly established, but
    # some honest vendors are recent too — recency alone must not be a
    # perfect tell (see decoy #6, which is deliberately a recent vendor).
    for name in VENDOR_NAME_POOL:
        rfc = make_rfc(rng)
        registered = draw_registered_date(rng, estate._period_start, recent_prob=0.20)
        v = estate.add_vendor(rfc, name, registered)
        if rng.random() < 0.6:
            estate.add_contract(rfc, registered,
                                 rng.uniform(200000, 900000),
                                 f"Contrato marco de {v['category'].lower()}, cuota o entregables periodicos")

    # Employees.
    for name in EMPLOYEE_NAME_POOL:
        hire = rng_choice_weighted_date(rng, date(2018, 1, 1), date(2025, 12, 31)).isoformat()
        estate.add_employee(name, rng.choice(ROLES), hire)

    # Background invoices: expenses from honest vendors + revenue to clients.
    for v in estate.vendors:
        has_contract = any(c["vendor_rfc"] == v["rfc"] for c in estate.contracts)
        n_invoices = rng.randint(3, 9)
        for _ in range(n_invoices):
            dt = estate.rand_date()
            subtotal = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
            metodo = rng.choice(METODO_PAGO)
            inv = estate.add_invoice(
                v["rfc"], estate.company_rfc, dt, subtotal,
                concepto_texto(rng, v["category"], GENERIC_PROB_HONESTO), metodo_pago=metodo,
            )
            requester = rng.choice(EMPLOYEE_NAME_POOL)
            # A small, legitimate slice of routine/low-value purchasing gets
            # delegated so the same person requests and approves — this is
            # the same raw signal threshold_splitting/kickback use, so it
            # must not be exclusive to fraud or a single decoy: real
            # organizations delegate small recurring purchases too.
            if rng.random() < 0.08:
                approver = requester
            else:
                approver = rng.choice([a for a in COMPANY_APPROVERS])
            if has_contract or rng.random() < 0.5:
                estate.add_po(v["rfc"], dt, inv["total"], requester, approver,
                              f"{v['category']} segun contrato/solicitud")
            estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                    f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                    f"CC-{rng.randint(100,300)}", approver)
            # Payment traceability: about 15% of routine invoices go
            # untracked (late reconciliation, manual payment run not yet
            # matched, etc.) regardless of metodo_pago — this must overlap
            # with fraud's own untracked rate rather than sit at a fixed
            # ~90-100% that a classifier can key off of.
            if rng.random() < 0.85:
                pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 30))).isoformat()
                estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"],
                                    inv["total"], f"Pago factura {inv['uuid'][:8]}")

    # Background revenue invoices to clients (so revenue_inflation has a
    # normal baseline to stand out against). Each client gets a VARIABLE
    # number of invoices (1-5) instead of always exactly one — otherwise
    # "how many invoices does this client have" becomes a perfect,
    # zero-overlap separator for revenue_inflation (which always plants
    # 3-5) on its own, regardless of whether any of them went uncollected.
    # ~14 clients * ~2.1 invoices average keeps roughly the same total
    # invoice volume as the old fixed 25x1.
    for _ in range(14):
        client_rfc = make_rfc(rng, persona_moral=True)
        n_invoices = rng.randint(1, 5)
        for _ in range(n_invoices):
            dt = estate.rand_date()
            subtotal = draw_amount(rng, aml, *BAND_REVENUE)
            inv = estate.add_invoice(estate.company_rfc, client_rfc, dt, subtotal,
                                      "Venta de servicios", metodo_pago=rng.choice(METODO_PAGO))
            estate.add_ledger_pair(dt, "4000", "Ingresos", inv["total"],
                                    f"Ingreso factura {inv['uuid'][:8]}", inv["uuid"],
                                    "CC-100 Ventas", rng.choice(COMPANY_APPROVERS), is_revenue=True)
            # Honest clients do NOT all pay inside the period. An invoice
            # issued near period close and still outstanding at cutoff is
            # ordinary accounts receivable, not fraud — and before this,
            # 100% of honest revenue was collected, which made "uncollected
            # at period end" a perfect stand-in for revenue_inflation (see
            # SOBRE_EL_MODELO.md). Collection probability now depends on how
            # close to the cutoff the invoice was issued, for honest clients
            # and for the scheme alike.
            dias_al_cierre = (estate._period_end - date.fromisoformat(dt)).days
            cobro_prob = 0.45 if dias_al_cierre <= 30 else 0.92
            if rng.random() < cobro_prob:
                pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
                estate.add_bank_txn(pay_date, client_rfc[:18].ljust(18, "0"), estate.company_clabe,
                                     inv["total"], f"Cobro factura {inv['uuid'][:8]}")


def build_sat_status_population(estate: Estate, sat_pool, aml: "AMLSimSeed"):
    """Plants a few REAL 69-B RFCs as ordinary vendors (full invoicing, PO,
    ledger and payment history).

    estate_schema.sql's efos_list.status is ONLY 'definitivo' | 'presunto'
    — those are the two real SAT categories the official schema defines,
    and the only ones a judge's own held-out estate will ever contain.
    'Desvirtuado' and 'Sentencia Favorable' are real, government-confirmed
    CLEARED outcomes and stay excellent decoy material (a real RFC that WAS
    on the 69-B radar and came out clean is exactly the kind of
    honest-but-suspicious-looking vendor a decoy set needs) — but they must
    NEVER be written into efos_list, since that column can't hold a value
    the official schema doesn't define, and a model trained on a status the
    judges' estate can never produce would be trained on a distribution
    that doesn't exist in production.

    So: 'presunto' vendors go into efos_list with that real status (a
    genuinely unresolved case — a legitimate, schema-valid ambiguous
    signal). 'Desvirtuado'/'Favorable' vendors get the same honest
    treatment but are recorded ONLY as ground-truth decoy entries (returned
    here, appended to the estate's decoys list by generate()) — never as an
    efos_list row.

    Call this AFTER build_schemes so S1's phantom (definitivo) RFC is
    already excluded via the current vendor list. Returns a list of decoy
    dicts (same shape as build_decoys' entries) for the desvirtuado/
    favorable vendors planted.
    """
    rng = estate.rng
    used_rfcs = {v["rfc"] for v in estate.vendors}
    decoys_extra = []

    def pick(status_norm, n):
        pool = [r for r in sat_pool if r["status_norm"] == status_norm and r["rfc"] not in used_rfcs]
        rng.shuffle(pool)
        return pool[:n]

    def plant(r, category, pay_prob, add_to_efos_list):
        registered = draw_registered_date(rng, estate._period_start, recent_prob=0.25)
        v = estate.add_vendor(r["rfc"], r["legal_name"], registered, category=category)
        used_rfcs.add(r["rfc"])
        if add_to_efos_list and not any(e["rfc"] == r["rfc"] for e in estate.efos_list):
            estate.efos_list.append({"rfc": r["rfc"], "legal_name": r["legal_name"],
                                      "status": r["status_norm"], "publication_date": estate.rand_date()})
        if rng.random() < 0.6:
            estate.add_contract(r["rfc"], registered, rng.uniform(150000, 600000),
                                 f"Contrato de {category.lower()}")
        invs = []
        for _ in range(rng.randint(3, 7)):
            dt = estate.rand_date()
            subtotal = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
            inv = estate.add_invoice(r["rfc"], estate.company_rfc, dt, subtotal,
                                      concepto_texto(rng, category, GENERIC_PROB_HONESTO),
                                      metodo_pago=rng.choice(METODO_PAGO))
            requester = rng.choice(EMPLOYEE_NAME_POOL)
            approver = requester if rng.random() < 0.08 else rng.choice(COMPANY_APPROVERS)
            if rng.random() < 0.5:
                estate.add_po(r["rfc"], dt, inv["total"], requester, approver,
                              f"{category} segun contrato/solicitud")
            estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                    f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                    f"CC-{rng.randint(100,300)}", approver)
            if rng.random() < pay_prob:
                pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 30))).isoformat()
                estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"],
                                     inv["total"], f"Pago factura {inv['uuid'][:8]}")
            invs.append(inv["uuid"])
        return invs

    for r in pick("presunto", 2):
        plant(r, rng.choice(CATEGORIES), pay_prob=0.65, add_to_efos_list=True)

    for r in pick("desvirtuado", 2):
        invs = plant(r, rng.choice(CATEGORIES), pay_prob=0.85, add_to_efos_list=False)
        decoys_extra.append({
            "entity": f"RFC:{r['rfc']}", "signal": "exonerated_69b_history",
            "why_innocent": "RFC con historial real de investigacion 69-B, status 'Desvirtuado' "
                            "(el contribuyente desvirtuo la presuncion ante el SAT). No aparece en "
                            "efos_list de esta estate porque el schema oficial solo admite "
                            "'definitivo'/'presunto' para esa tabla.",
            "invoices": invs,
        })

    for r in pick("favorable", 2):
        invs = plant(r, rng.choice(CATEGORIES), pay_prob=0.85, add_to_efos_list=False)
        decoys_extra.append({
            "entity": f"RFC:{r['rfc']}", "signal": "exonerated_69b_history",
            "why_innocent": "RFC con historial real de investigacion 69-B, status 'Sentencia "
                            "Favorable' (el contribuyente gano en tribunales). No aparece en "
                            "efos_list de esta estate porque el schema oficial solo admite "
                            "'definitivo'/'presunto' para esa tabla.",
            "invoices": invs,
        })

    return decoys_extra


def build_schemes(estate: Estate, sat_pool, aml: AMLSimSeed):
    rng = estate.rng
    schemes = []
    definitivos = [r for r in sat_pool if r["status_norm"] == "definitivo"]

    # ---- S1 phantom_vendor: a real, definitivo 69-B RFC as the vendor. ----
    phantom = rng.choice(definitivos)
    already_listed = any(e["rfc"] == phantom["rfc"] for e in estate.efos_list)
    if not already_listed:
        estate.efos_list.append({"rfc": phantom["rfc"], "legal_name": phantom["legal_name"],
                                  "status": "definitivo", "publication_date": estate.rand_date()})
    phantom_registered = draw_registered_date(rng, estate._period_start, recent_prob=0.55)
    estate.add_vendor(phantom["rfc"], phantom["legal_name"], phantom_registered, category="Consultoria")
    # A minority of phantom vendors get a contract on paper too — a real
    # EFOS relationship is sometimes dressed up with a contract; the tell
    # is the efos_list match itself and the generic, undocumented invoices,
    # not the mere absence of a contract.
    # 60%, matching the efos_definitivo_con_materialidad decoy, whose
    # innocence narrative requires a contract — at 25% vs 60%, contract
    # presence was itself a tell.
    has_contract = rng.random() < 0.60
    if has_contract:
        estate.add_contract(phantom["rfc"], phantom_registered, rng.uniform(150000, 500000),
                             "Contrato de servicios de consultoria")
    invs, txns = [], []
    n_phantom_invoices = rng.randint(5, 8)
    for i in range(n_phantom_invoices):
        dt = estate.rand_date()
        amount = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
        inv = estate.add_invoice(phantom["rfc"], estate.company_rfc, dt, amount,
                                  concepto_texto(rng, "Consultoria", GENERIC_PROB_ESQUEMA),
                                  metodo_pago=rng.choice(METODO_PAGO))
        # A phantom operation is often dressed up with paperwork — not every
        # simulated invoice arrives naked. Before this the phantom had zero
        # POs in every estate, so "es_69b_definitivo AND num_ordenes_compra<=2"
        # identified the scheme perfectly (see SOBRE_EL_MODELO.md). The real
        # tell is the efos_list match plus the vague concepto, not the mere
        # absence of a purchase order.
        if rng.random() < 0.35:
            req_ph = rng.choice(EMPLOYEE_NAME_POOL)
            apr_ph = req_ph if rng.random() < 0.08 else rng.choice(COMPANY_APPROVERS)
            estate.add_po(phantom["rfc"], dt, inv["total"], req_ph, apr_ph,
                          "Servicios de consultoria segun solicitud")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                "CC-999 Sin centro definido", rng.choice(COMPANY_APPROVERS))
        # Keep the first invoice always reconciled (so the scheme always has
        # at least one cited exhibit); the rest have the same ~12% chance of
        # going untracked that honest vendors have, so payment traceability
        # overlaps between fraud and honest instead of being a clean tell.
        if i == 0 or rng.random() < 0.88:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 10))).isoformat()
            vendor_clabe = estate.vendors[-1]["bank_clabe"]
            txn = estate.add_bank_txn(pay_date, estate.company_clabe, vendor_clabe, inv["total"],
                                       f"Pago factura {inv['uuid'][:8]}")
            invs.append(inv["uuid"])
            txns.append(txn["txn_id"])
    peso_amount = round(sum(estate.bank_txns[-len(txns):][i]["amount"] for i in range(len(txns))), 2)
    signals = ["vendor en efos_list definitivo", "conceptos genericos"]
    signals.append("sin contrato ni orden de compra" if not has_contract else
                    "contrato existe pero sin entregables verificables")
    schemes.append({
        "scheme_id": "S1_phantom_vendor", "type": "phantom_vendor",
        "entities": [f"RFC:{phantom['rfc']}"],
        "supporting_invoices": invs, "supporting_txns": txns,
        "peso_amount": peso_amount, "difficulty": "easy",
        "_signals": signals,
    })

    # ---- S2 round_tripping: real AMLSim cycle topology, re-skinned. -------
    loop_vendor_registered = draw_registered_date(rng, estate._period_start, recent_prob=0.55)
    loop_vendor = estate.add_vendor(make_rfc(rng), "Intermediaria Comercial Reyna SA de CV",
                                     loop_vendor_registered)
    if rng.random() < 0.25:
        estate.add_contract(loop_vendor["rfc"], loop_vendor_registered, rng.uniform(150000, 500000),
                             "Contrato de intermediacion comercial")
    cycle_pesos = aml.cycle_pesos_in_range(rng, 3, *BAND_ROUND_TRIPPING)
    start_dt = estate.rand_date()
    initiating_amount = cycle_pesos[0]
    inv = estate.add_invoice(loop_vendor["rfc"], estate.company_rfc, start_dt, initiating_amount,
                              "Servicios de intermediacion comercial", metodo_pago=rng.choice(METODO_PAGO))
    estate.add_ledger_pair(start_dt, "5000", "Gastos operativos", inv["total"],
                            f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                            "CC-200 Comercial", rng.choice(COMPANY_APPROVERS))
    hop_nodes = [estate.company_clabe, loop_vendor["bank_clabe"]]
    for _ in range(len(cycle_pesos) - 1):
        hop_nodes.append(make_clabe(rng))
    hop_nodes.append(estate.company_clabe)  # closes the loop
    round_txns = []
    dt_cursor = date.fromisoformat(start_dt)
    round_txns.append(estate.add_bank_txn(dt_cursor.isoformat(), estate.company_clabe,
                                           loop_vendor["bank_clabe"], inv["total"],
                                           f"Pago factura {inv['uuid'][:8]}")["txn_id"])
    for i in range(1, len(hop_nodes) - 1):
        dt_cursor += timedelta(days=rng.randint(1, 4))
        amt = cycle_pesos[min(i, len(cycle_pesos) - 1)]
        txn = estate.add_bank_txn(dt_cursor.isoformat(), hop_nodes[i], hop_nodes[i + 1],
                                   amt, "Transferencia entre cuentas relacionadas")
        round_txns.append(txn["txn_id"])
    # The loop vendor also invoices ordinary work. Before this it had
    # EXACTLY one invoice in every estate (the cycle's initiating invoice),
    # so "num_facturas <= 2" identified round_tripping on its own — an
    # intermediary that only ever issues a single invoice is an artifact of
    # how we planted it, not of how round-tripping works. These extra
    # invoices are deliberately NOT part of the scheme's supporting_invoices
    # or peso_amount: the accusation still reconciles against the cycle
    # alone.
    for _ in range(rng.randint(2, 5)):
        dt_extra = estate.rand_date()
        extra_amount = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
        extra_inv = estate.add_invoice(
            loop_vendor["rfc"], estate.company_rfc, dt_extra, extra_amount,
            concepto_texto(rng, "Intermediacion comercial", GENERIC_PROB_HONESTO),
            metodo_pago=rng.choice(METODO_PAGO))
        requester_x = rng.choice(EMPLOYEE_NAME_POOL)
        approver_x = requester_x if rng.random() < 0.08 else rng.choice(COMPANY_APPROVERS)
        if rng.random() < 0.5:
            estate.add_po(loop_vendor["rfc"], dt_extra, extra_inv["total"], requester_x, approver_x,
                          "Intermediacion comercial segun solicitud")
        estate.add_ledger_pair(dt_extra, "5000", "Gastos operativos", extra_inv["total"],
                                f"Registro factura {extra_inv['uuid'][:8]}", extra_inv["uuid"],
                                "CC-200 Comercial", approver_x)
        if rng.random() < 0.85:
            pay_x = (date.fromisoformat(dt_extra) + timedelta(days=rng.randint(1, 30))).isoformat()
            estate.add_bank_txn(pay_x, estate.company_clabe, loop_vendor["bank_clabe"],
                                 extra_inv["total"], f"Pago factura {extra_inv['uuid'][:8]}")
    schemes.append({
        "scheme_id": "S2_round_tripping", "type": "round_tripping",
        "entities": [f"RFC:{loop_vendor['rfc']}"],
        "supporting_invoices": [inv["uuid"]], "supporting_txns": round_txns,
        "peso_amount": inv["total"], "difficulty": "medium",
        "_signals": ["ciclo que regresa a la CLABE de la empresa",
                     "monto se conserva casi intacto en la cadena",
                     "topologia y montos tomados de un ciclo real de AMLSim (20K_cycle200)"],
    })

    # ---- S3 revenue_inflation: end-of-period revenue with no receipt. ----
    client_rfc = make_rfc(rng)
    invs = []
    for _ in range(rng.randint(3, 5)):
        dt = (estate._period_end - timedelta(days=rng.randint(0, 5))).isoformat()
        amount = draw_amount(rng, aml, *BAND_REVENUE)
        inv = estate.add_invoice(estate.company_rfc, client_rfc, dt, amount,
                                  "Venta de servicios de fin de periodo", metodo_pago=rng.choice(METODO_PAGO))
        estate.add_ledger_pair(dt, "4000", "Ingresos", inv["total"],
                                f"Ingreso factura {inv['uuid'][:8]}", inv["uuid"],
                                "CC-100 Ventas", rng.choice(COMPANY_APPROVERS), is_revenue=True)
        invs.append(inv["uuid"])
    peso_amount = round(sum(i["total"] for i in estate.invoices if i["uuid"] in invs), 2)
    schemes.append({
        "scheme_id": "S3_revenue_inflation", "type": "revenue_inflation",
        "entities": [f"RFC:{client_rfc}"],
        "supporting_invoices": invs, "supporting_txns": [],
        "peso_amount": peso_amount, "difficulty": "easy",
        "_signals": ["facturas de ingreso al cierre del periodo sin cobro en bank_txns",
                     "cliente nuevo, sin historial de cobro previo"],
    })

    # ---- S4 threshold_splitting: many POs just under a threshold. -------
    threshold = 50000.0
    split_vendor_registered = draw_registered_date(rng, estate._period_start, recent_prob=0.55)
    split_vendor = estate.add_vendor(make_rfc(rng), "Suministros Fraccionados del Valle SA de CV",
                                      split_vendor_registered)
    # 80%, not 25%: the honest near-twin of this scheme (decoy
    # below_approval_threshold_pattern) NEEDS a standing contract for its
    # innocence to be true, so if the scheme almost never had one,
    # num_contratos separated the two perfectly. A supplier being split
    # against a framework contract is realistic anyway.
    if rng.random() < 0.80:
        estate.add_contract(split_vendor["rfc"], split_vendor_registered, rng.uniform(150000, 500000),
                             "Contrato marco de suministros")
    requester = rng.choice(EMPLOYEE_NAME_POOL)
    # Same requester/approver is the signal, but NOT on every single order:
    # at 100% it was a constant that no honest vendor could ever reach,
    # which turned pct_po_mismo_requester_approver into a perfect separator.
    # A real splitter still routes some orders through a second signature,
    # precisely so the pattern doesn't look mechanical.
    MISMO_FIRMANTE_PROB = 0.70
    invs, txns = [], []
    window_start = rng_choice_weighted_date(rng, date(2026, 3, 1), date(2026, 5, 1))
    n_split_pos = rng.randint(10, 14)
    for i in range(n_split_pos):
        dt = (window_start + timedelta(days=i * rng.randint(2, 5))).isoformat()
        # Not every order sits just under the limit. At 100% "just under",
        # pct_po_justo_bajo_umbral_50k became a near-perfect separator no
        # honest vendor could reach; a real splitter also buys ordinary
        # small items from the same supplier.
        if rng.random() < 0.75:
            amount = threshold - rng.uniform(200, 3500)
        else:
            amount = rng.uniform(6000, 41000)
        approver = requester if rng.random() < MISMO_FIRMANTE_PROB else rng.choice(COMPANY_APPROVERS)
        estate.add_po(split_vendor["rfc"], dt, amount, requester, approver,
                      "Suministros diversos, folio individual")
        inv = estate.add_invoice(split_vendor["rfc"], estate.company_rfc, dt,
                                  round(amount / (1 + IVA_RATE), 2),
                                  concepto_texto(rng, "Suministros", GENERIC_PROB_ESQUEMA),
                                  metodo_pago=rng.choice(METODO_PAGO))
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                "CC-150 Suministros", approver)
        if i < 2 or rng.random() < 0.88:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 5))).isoformat()
            txn = estate.add_bank_txn(pay_date, estate.company_clabe, split_vendor["bank_clabe"],
                                       inv["total"], f"Pago factura {inv['uuid'][:8]}")
            invs.append(inv["uuid"])
            txns.append(txn["txn_id"])
    peso_amount = round(sum(t["amount"] for t in estate.bank_txns if t["txn_id"] in txns), 2)
    schemes.append({
        "scheme_id": "S4_threshold_splitting", "type": "threshold_splitting",
        "entities": [f"RFC:{split_vendor['rfc']}"],
        "supporting_invoices": invs, "supporting_txns": txns,
        "peso_amount": peso_amount, "difficulty": "easy",
        "_signals": [f"{len(invs)} ordenes justo por debajo de {threshold:,.0f} MXN",
                     "mismo solicitante y aprobador", "concentradas en pocas semanas"],
    })

    # ---- S5 kickback: same requester/approver, vendor pays an employee. --
    kb_vendor_registered = draw_registered_date(rng, estate._period_start, recent_prob=0.55)
    kb_vendor = estate.add_vendor(make_rfc(rng), "Servicios Preferentes del Poniente SA de CV",
                                   kb_vendor_registered)
    if rng.random() < 0.25:
        estate.add_contract(kb_vendor["rfc"], kb_vendor_registered, rng.uniform(150000, 500000),
                             "Contrato de servicios especializados")
    kb_employee = estate.add_employee(rng.choice(EMPLOYEE_NAME_POOL) + " (compras)",
                                       "Comprador Senior", "2022-02-01")
    invs, txns, kickback_txns = [], [], []
    n_kb_invoices = rng.randint(4, 6)
    for i in range(n_kb_invoices):
        dt = estate.rand_date()
        amount = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
        inv = estate.add_invoice(kb_vendor["rfc"], estate.company_rfc, dt, amount,
                                  "Servicios especializados, tarifa preferente", metodo_pago=rng.choice(METODO_PAGO))
        # Same reason as threshold_splitting: the buyer signing his own
        # orders is the signal, but at a literal 100% it was a constant no
        # honest vendor could reach. Some orders carry a second signature.
        kb_approver = (kb_employee["name"] if rng.random() < 0.70
                       else rng.choice(COMPANY_APPROVERS))
        estate.add_po(kb_vendor["rfc"], dt, inv["total"], kb_employee["name"], kb_approver,
                      "Servicios especializados por encima de tarifa de mercado")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                "CC-300 Compras", kb_employee["name"])
        # The vendor->employee kickback transfer is the actual fraud tell
        # and always happens; the ordinary invoice payment that funds it
        # has the same ~12% untracked chance as everywhere else so payment
        # traceability alone can't separate this vendor from an honest one.
        if i == 0 or rng.random() < 0.88:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 6))).isoformat()
            txn = estate.add_bank_txn(pay_date, estate.company_clabe, kb_vendor["bank_clabe"],
                                       inv["total"], f"Pago factura {inv['uuid'][:8]}")
            invs.append(inv["uuid"])
            txns.append(txn["txn_id"])
        else:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 6))).isoformat()
        kb_amt = aml.amounts(rng, 1, scale=rng.uniform(600, 1100))[0]
        kb_pay_date = (date.fromisoformat(pay_date) + timedelta(days=rng.randint(1, 3))).isoformat()
        kb_txn = estate.add_bank_txn(kb_pay_date, kb_vendor["bank_clabe"], kb_employee["bank_clabe"],
                                      kb_amt, "Transferencia personal")
        kickback_txns.append(kb_txn["txn_id"])
    peso_amount = round(sum(t["amount"] for t in estate.bank_txns if t["txn_id"] in txns), 2)
    schemes.append({
        "scheme_id": "S5_kickback", "type": "kickback",
        "entities": [f"RFC:{kb_vendor['rfc']}", kb_employee["emp_id"]],
        "supporting_invoices": invs, "supporting_txns": txns + kickback_txns,
        "peso_amount": peso_amount, "difficulty": "medium",
        "_signals": ["mismo requester y approver", "precio por encima de mercado",
                     "transferencias del proveedor a la CLABE del empleado, "
                     "montos tomados de transacciones reales marcadas isFraud en AMLSim"],
    })

    return schemes


def build_decoys(estate: Estate, sat_pool, aml: "AMLSimSeed"):
    rng = estate.rng
    decoys = []

    # 1. below threshold, but that's the honest per-unit contract price.
    v = estate.add_vendor(make_rfc(rng), "Fletes Contractuales del Norte SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Transporte")
    estate.add_contract(v["rfc"], "2021-06-01", 480000.0,
                         "Tarifa fija por viaje, facturacion quincenal")
    invs = []
    # A NEAR-TWIN of threshold_splitting on every observable feature: same
    # "just under 50k" band, same order count, and — in about half the
    # estates — the same concentrated window and the same rate of orders
    # signed by whoever requested them (a contract manager with delegated
    # authority). The ONLY thing that differs is the ground truth: here the
    # per-trip rate is the price actually agreed in a standing contract.
    # Drawing the decoy from DIFFERENT distributions than the scheme is what
    # kept this class perfectly separable (see SOBRE_EL_MODELO.md); a decoy
    # is only worth planting if it can actually fool the model.
    # Always concentrated, like the scheme: "facturacion quincenal" in this
    # decoy's own contract literally means regular, clustered invoicing, so
    # spreading it across the year was both unfaithful to its narrative and
    # the last thing letting a model tell the twin apart.
    concentrado = True
    win0 = rng_choice_weighted_date(rng, date(2026, 3, 1), date(2026, 5, 1))
    req_flete = rng.choice(EMPLOYEE_NAME_POOL)
    mismo_prob_flete = 0.70 if rng.random() < 0.5 else 0.05
    gen_prob_flete = GENERIC_PROB_ESQUEMA if rng.random() < 0.5 else GENERIC_PROB_HONESTO
    for i in range(rng.randint(10, 14)):
        dt = ((win0 + timedelta(days=i * rng.randint(2, 5))).isoformat()
              if concentrado else estate.rand_date())
        # NOTE: add_invoice takes the SUBTOTAL and adds IVA, while the PO is
        # raised for the invoice TOTAL — so to land the ORDER inside the
        # "just under 50k" band the subtotal has to be the pre-IVA figure,
        # exactly the way threshold_splitting computes it. Setting the
        # subtotal itself to ~47k (an earlier attempt at this decoy) pushed
        # the order to ~55k, above the limit, which is why this decoy scored
        # 0.0 on pct_po_justo_bajo_umbral_50k and never actually competed
        # with the scheme.
        # Same 75/25 mix of "just under the limit" vs ordinary smaller
        # orders the scheme uses, and the same metodo_pago and concepto
        # distributions. Every incidental parameter this decoy hardcoded
        # (always PUE, always the same concepto string, always in-band)
        # became the feature that gave it away — pct_facturas_ppd was the
        # third one found this way. A decoy only works if it is drawn from
        # the same distributions as the scheme on everything observable.
        if rng.random() < 0.75:
            monto_orden = 50000.0 - rng.uniform(200, 3500)
        else:
            monto_orden = rng.uniform(6000, 41000)
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt,
                                  round(monto_orden / (1 + IVA_RATE), 2),
                                  concepto_texto(rng, "Fletes", gen_prob_flete),
                                  metodo_pago=rng.choice(METODO_PAGO))
        apr_flete = (req_flete if rng.random() < mismo_prob_flete
                     else rng.choice([a for a in COMPANY_APPROVERS]))
        estate.add_po(v["rfc"], dt, inv["total"], req_flete, apr_flete, "Flete segun contrato")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-400 Logistica",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 20))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "below_approval_threshold_pattern",
                    "why_innocent": "La tarifa por viaje esta fijada en contrato vigente; los montos "
                                    "quedan bajo cualquier umbral por precio pactado, no por fraccionamiento, "
                                    "y el solicitante y el aprobador son distintos.",
                    "invoices": invs})

    # 2. purchase without PO, but small one-off with full paper trail.
    v = estate.add_vendor(make_rfc(rng), "Refacciones Rapidas Escobedo SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Mantenimiento")
    dt = estate.rand_date()
    inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, 8500.0,
                              "Refaccion urgente para linea de produccion", metodo_pago="PUE")
    estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                            f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-100 Produccion",
                            rng.choice(COMPANY_APPROVERS))
    estate.add_bank_txn((date.fromisoformat(dt) + timedelta(days=3)).isoformat(),
                         estate.company_clabe, v["bank_clabe"], inv["total"], "Pago urgente")
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "purchase_without_po",
                    "why_innocent": "Compra unica de monto menor, por debajo del umbral que exige "
                                    "orden de compra formal; existe factura y registro contable completos.",
                    "invoices": [inv["uuid"]]})

    # 3. identical round amounts, but it's a fixed monthly fee under contract.
    v = estate.add_vendor(make_rfc(rng), "Seguridad y Vigilancia Cumbres SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Seguridad")
    estate.add_contract(v["rfc"], "2022-09-01", 720000.0, "Iguala mensual fija por vigilancia")
    invs = []
    for m in range(8):
        dt = (date(2026, 1, 1) + timedelta(days=30 * m)).isoformat()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, 60000.0,
                                  "Iguala mensual de vigilancia segun contrato", metodo_pago="PUE")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-500 Seguridad",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "identical_round_amounts",
                    "why_innocent": "Iguala mensual fija amparada por contrato vigente; el monto "
                                    "identico cada mes es la cuota pactada, no una senal de fraccionamiento.",
                    "invoices": invs})

    # 4. employee shares a bank but there's no actual transfer.
    v = estate.add_vendor(make_rfc(rng), "Insumos de Oficina Garza Sada SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Papeleria")
    estate.add_contract(v["rfc"], "2020-04-01", 150000.0, "Suministro trimestral de papeleria")
    emp = estate.add_employee(rng.choice(EMPLOYEE_NAME_POOL) + " (finanzas)", "Auxiliar Contable", "2020-01-15")
    invs = []
    for _ in range(4):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(9000, 15000),
                                  "Papeleria trimestral", metodo_pago="PUE")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-600 Administracion",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "employee_vendor_bank_linkage",
                    "why_innocent": f"Comparte institucion bancaria con {emp['emp_id']} pero no cuenta; "
                                    "no existe transferencia entre el proveedor y el empleado, y el "
                                    "gasto esta amparado por contrato.",
                    "invoices": invs})

    # 5. generic concept, but a real long-standing contract with deliverables.
    v = estate.add_vendor(make_rfc(rng), "Asesoria Fiscal Permanente SC",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Consultoria")
    estate.add_contract(v["rfc"], "2020-02-01", 960000.0,
                         "Contrato de consultoria fiscal, entregables trimestrales")
    invs = []
    for _ in range(6):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(35000, 55000),
                                  "Servicios de consultoria", metodo_pago="PUE")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-700 Fiscal",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "generic_service_concept",
                    "why_innocent": "Concepto generico en la factura, pero respaldado por un contrato "
                                    "de consultoria fiscal vigente desde hace mas de tres anos con "
                                    "entregables trimestrales documentados.",
                    "invoices": invs})

    # 6. new vendor spend concentration, but PO+contract match every invoice.
    v = estate.add_vendor(make_rfc(rng), "Instalaciones Electricas del Bajio SA de CV",
                           rng_choice_weighted_date(rng, date(2025, 10, 1), date(2026, 1, 1)).isoformat(),
                           category="Construccion")
    estate.add_contract(v["rfc"], v["registered_date"], 600000.0,
                         "Contrato marco por fases, entregables verificables")
    invs = []
    for _ in range(9):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(30000, 70000),
                                  "Instalacion electrica, fase del proyecto", metodo_pago="PUE")
        estate.add_po(v["rfc"], dt, inv["total"], rng.choice(EMPLOYEE_NAME_POOL),
                      rng.choice(COMPANY_APPROVERS), "Fase del proyecto segun contrato")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-800 Obra",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "new_vendor_spend_concentration",
                    "why_innocent": "Contrato marco firmado con entregables por fase; cada factura "
                                    "tiene una orden de compra correspondiente que documenta la fase.",
                    "invoices": invs})

    # 7. efos_list match, but publication postdates every transaction.
    # Uses 'presunto' — the only OTHER schema-valid efos_list status besides
    # 'definitivo' — never 'desvirtuado'/'favorable', which never belong in
    # efos_list at all (see build_sat_status_population).
    existing_rfcs = {v["rfc"] for v in estate.vendors}
    cleared_pool = [r for r in sat_pool if r["status_norm"] == "presunto" and r["rfc"] not in existing_rfcs]
    r = rng.choice(cleared_pool) if cleared_pool else rng.choice(sat_pool)
    v = estate.add_vendor(r["rfc"], r["legal_name"], "2019-01-01", category="Consultoria")
    estate.add_contract(v["rfc"], "2019-02-01", 300000.0, "Contrato de servicios con materialidad")
    late_pub = (estate._period_end + timedelta(days=60)).isoformat()
    already = any(e["rfc"] == v["rfc"] for e in estate.efos_list)
    if not already:
        estate.efos_list.append({"rfc": v["rfc"], "legal_name": v["legal_name"],
                                  "status": r["status_norm"], "publication_date": late_pub})
    invs = []
    for _ in range(5):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(20000, 40000),
                                  "Servicios de consultoria con entregable", metodo_pago="PUE")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-700 Fiscal",
                                rng.choice(COMPANY_APPROVERS))
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "efos_list_match",
                    "why_innocent": "La publicacion en el listado 69-B es posterior a todas las "
                                    "operaciones con este proveedor; no podia conocerse al contratar, "
                                    "y existe contrato con materialidad documentada.",
                    "invoices": invs})

    # 8. cash channel payments, but small, documented, long-standing vendor.
    v = estate.add_vendor(make_rfc(rng), "Limpieza y Mantenimiento Escobedo SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Limpieza")
    invs = []
    for _ in range(8):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(2000, 6000),
                                  "Servicio de limpieza semanal", metodo_pago="PUE", forma_pago="01")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-600 Administracion",
                                rng.choice(COMPANY_APPROVERS))
        estate.add_bank_txn(dt, estate.company_clabe, v["bank_clabe"], inv["total"],
                             f"Pago en efectivo factura {inv['uuid'][:8]}", channel="efectivo")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "cash_channel_payments",
                    "why_innocent": "Pagos en efectivo de bajo monto a un proveedor con anos de "
                                    "historial; cada uno tiene CFDI y registro contable correspondiente.",
                    "invoices": invs})

    # 9. same requester and approver, but a documented, authorized delegation
    # for a small, capped category — the same raw signal used by
    # threshold_splitting and kickback, without the fraud behind it.
    v = estate.add_vendor(make_rfc(rng), "Ferreteria Industrial Guadalupe SA de CV",
                           draw_registered_date(rng, estate._period_start, recent_prob=0.55),
                           category="Mantenimiento")
    estate.add_contract(v["rfc"], "2021-10-01", 96000.0,
                         "Contrato de reposicion de herramienta menor, delegacion autorizada")
    approver_delegado = rng.choice(EMPLOYEE_NAME_POOL) + " (jefe de mantenimiento)"
    invs = []
    for _ in range(6):
        dt = estate.rand_date()
        inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, rng.uniform(4000, 9000),
                                  "Reposicion de herramienta menor", metodo_pago=rng.choice(METODO_PAGO))
        estate.add_po(v["rfc"], dt, inv["total"], approver_delegado, approver_delegado,
                      "Reposicion de herramienta, delegacion de compra menor autorizada por politica interna")
        estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                f"Registro factura {inv['uuid'][:8]}", inv["uuid"], "CC-900 Mantenimiento",
                                approver_delegado)
        if rng.random() < 0.9:
            pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 15))).isoformat()
            estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"], inv["total"],
                                 f"Pago factura {inv['uuid'][:8]}")
        invs.append(inv["uuid"])
    decoys.append({"entity": f"RFC:{v['rfc']}", "signal": "same_requester_approver",
                    "why_innocent": "El mismo puesto solicita y aprueba por politica interna documentada "
                                    "para compras menores de herramienta; el monto por orden esta muy por "
                                    "debajo de cualquier umbral de aprobacion y hay contrato vigente.",
                    "invoices": invs})

    # 10. real 'definitivo' 69-B status, but the commercial relationship
    # ended before this period — a second, genuinely honest 'definitivo'
    # example. Without this, efos_list status == 'definitivo' is a perfect,
    # zero-overlap stand-in for "this IS the phantom_vendor scheme" (the
    # generator otherwise never writes 'definitivo' anywhere else), which
    # made es_69b_definitivo a single-feature separator for phantom_vendor
    # in the ML model (see SOBRE_EL_MODELO.md). This vendor has ZERO
    # invoices/POs/payments in the audited period on purpose.
    existing_rfcs_def = {v["rfc"] for v in estate.vendors} | {e["rfc"] for e in estate.efos_list}
    definitivo_pool = [r for r in sat_pool if r["status_norm"] == "definitivo" and r["rfc"] not in existing_rfcs_def]
    if definitivo_pool:
        r = rng.choice(definitivo_pool)
        cat = rng.choice(CATEGORIES)
        # Same registration-date distribution as phantom_vendor: an always-old
        # vendor made dias_antiguedad_al_facturar the last thing separating
        # this decoy from the scheme it is supposed to be a twin of.
        old_registered = draw_registered_date(rng, estate._period_start, recent_prob=0.55)
        v = estate.add_vendor(r["rfc"], r["legal_name"], old_registered, category=cat)
        estate.efos_list.append({"rfc": r["rfc"], "legal_name": r["legal_name"], "status": "definitivo",
                                  "publication_date": (estate._period_start - timedelta(days=rng.randint(30, 200))).isoformat()})
        # Same idea as the flete decoy: in about half the estates this
        # legitimate vendor ALSO captures its concepto text vaguely and
        # ALSO lacks a purchase order on most invoices, i.e. it looks
        # exactly like phantom_vendor on every observable feature. Only the
        # ground truth separates them.
        gen_prob_dec = GENERIC_PROB_ESQUEMA if rng.random() < 0.5 else GENERIC_PROB_HONESTO
        po_prob_dec = 0.35 if rng.random() < 0.5 else 0.75
        if rng.random() < 0.6:
            estate.add_contract(v["rfc"], old_registered, rng.uniform(200000, 600000),
                                 f"Contrato de {cat.lower()} con entregables y actas de recepcion")
        invs = []
        for _ in range(rng.randint(5, 8)):
            dt = estate.rand_date()
            subtotal = draw_amount(rng, aml, *BAND_SERVICIO_RECURRENTE)
            inv = estate.add_invoice(v["rfc"], estate.company_rfc, dt, subtotal,
                                      concepto_texto(rng, cat, gen_prob_dec),
                                      metodo_pago=rng.choice(METODO_PAGO))
            req = rng.choice(EMPLOYEE_NAME_POOL)
            apr = req if rng.random() < 0.08 else rng.choice(COMPANY_APPROVERS)
            if rng.random() < po_prob_dec:
                estate.add_po(v["rfc"], dt, inv["total"], req, apr,
                              f"{cat} segun contrato, con acta de recepcion")
            estate.add_ledger_pair(dt, "5000", "Gastos operativos", inv["total"],
                                    f"Registro factura {inv['uuid'][:8]}", inv["uuid"],
                                    f"CC-{rng.randint(100,300)}", apr)
            if rng.random() < 0.88:
                pay_date = (date.fromisoformat(dt) + timedelta(days=rng.randint(1, 25))).isoformat()
                estate.add_bank_txn(pay_date, estate.company_clabe, v["bank_clabe"],
                                     inv["total"], f"Pago factura {inv['uuid'][:8]}")
            invs.append(inv["uuid"])
        decoys.append({
            "entity": f"RFC:{v['rfc']}", "signal": "efos_definitivo_con_materialidad",
            "why_innocent": "Aparece como 'definitivo' en el listado 69-B, pero el servicio SI se "
                            "presto: hay contrato con entregables, orden de compra por cada factura "
                            "con solicitante y aprobador distintos, registro contable y pago "
                            "rastreable. El status en efos_list hace no deducible el gasto ante el "
                            "SAT, que es un problema fiscal de esta empresa, no evidencia de que "
                            "esta empresa haya montado un esquema de proveedor fantasma.",
            "invoices": invs,
        })

    return decoys


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def generate(seed: int, db_dir: Path, gt_dir: Path, sat_csv: Path, amlsim_tgz: Path):
    sat_pool = load_sat_69b(sat_csv)
    aml = AMLSimSeed(amlsim_tgz)

    estate = Estate(seed)
    estate.company_rfc = make_rfc(estate.rng, persona_moral=True)
    estate.company_clabe = make_clabe(estate.rng)

    build_background(estate, sat_pool, aml)
    schemes = build_schemes(estate, sat_pool, aml)
    decoys_extra_sat = build_sat_status_population(estate, sat_pool, aml)
    decoys = build_decoys(estate, sat_pool, aml)
    decoys.extend(decoys_extra_sat)

    db_dir.mkdir(parents=True, exist_ok=True)
    gt_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{seed:04d}"
    db_path = db_dir / f"estate_{tag}.db"
    gt_path = gt_dir / f"gt_{tag}.json"

    estate.to_sqlite(db_path)

    ground_truth = {
        "seed": seed,
        "company_rfc": estate.company_rfc,
        "schemes": schemes,
        "decoys": decoys,
    }
    gt_path.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False))

    print(f"seed {seed}: company_rfc={estate.company_rfc}")
    print(f"  vendors={len(estate.vendors)} employees={len(estate.employees)} "
          f"contracts={len(estate.contracts)} purchase_orders={len(estate.purchase_orders)}")
    print(f"  invoices={len(estate.invoices)} ledger_entries={len(estate.ledger)} "
          f"bank_txns={len(estate.bank_txns)} efos_list={len(estate.efos_list)}")
    print(f"  schemes planted: {len(schemes)}  decoys planted: {len(decoys)}")
    print(f"  wrote {db_path}")
    print(f"  wrote {gt_path}  <-- ground truth. Keep this OUT of the agent's import path.")
    return db_path, gt_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True, help="Deterministic seed for the estate.")
    ap.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR, help="Where to write estate_NNNN.db.")
    ap.add_argument("--gt-dir", type=Path, default=DEFAULT_GT_DIR, help="Where to write gt_NNNN.json.")
    ap.add_argument("--sat-csv", type=Path, default=DEFAULT_SAT_CSV, help="Path to Listado_completo_69-B.csv.")
    ap.add_argument("--amlsim-tgz", type=Path, default=DEFAULT_AMLSIM_TGZ,
                     help="Path to an AMLSim sample tgz (nodes.csv/transactions.csv inside).")
    args = ap.parse_args()

    if not args.sat_csv.exists():
        sys.exit(f"SAT 69-B CSV not found: {args.sat_csv}")
    if not args.amlsim_tgz.exists():
        sys.exit(f"AMLSim sample tgz not found: {args.amlsim_tgz}")
    if not SCHEMA_SQL.exists():
        sys.exit(f"estate_schema.sql not found: {SCHEMA_SQL}")

    generate(args.seed, args.db_dir, args.gt_dir, args.sat_csv, args.amlsim_tgz)


if __name__ == "__main__":
    main()
