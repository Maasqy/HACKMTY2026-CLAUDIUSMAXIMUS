"""
src/tools/estate_access.py

The Access Layer. This is the ONLY bridge between the LLM and the estate's
SQLite database. The agent never sees a table, a column, or a SQL string —
it calls a strictly-typed Python function with strictly-typed arguments and
gets back a strictly-typed dataclass (see models.py). If a function here
can't answer a question, the answer is "add a new tool", never "let the
model write SQL".

Why: an LLM asked to write SQL against an unfamiliar schema hallucinates
column names and produces syntax errors it cannot always self-correct on a
sandboxed, offline model. A fixed, typed tool surface turns "wrong query"
into "wrong argument to a function with type hints" — a class of error the
model makes far less often, and one `mypy`/`pydantic` can catch before the
tool is ever called.

Design rules this module holds itself to:
  1. Opens the estate strictly read-only (SQLite URI mode=ro). A tool that
     could write to the estate could also write to the evidence.
  2. The estate path is a constructor argument, resolved at run time. There
     are no hardcoded paths anywhere in this file — the track's rules fail
     any submission that hardcodes one.
  3. Every query is parameterized (`?` placeholders). No f-string ever
     builds a WHERE clause from caller input.
  4. This module imports nothing from eval/ and never references the
     evaluation answer key by name — it has no reason to.
  5. Every public method has a docstring written for the LLM that will call
     it, not just for a human reading the source — see tool_specs.py, which
     turns these into callable-tool descriptors via introspection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import (
    BankTxn,
    ClabeOwner,
    CompanyProfile,
    Contract,
    EfosRecord,
    Employee,
    Invoice,
    LedgerEntry,
    PurchaseOrder,
    Vendor,
    VendorProfile,
)


class EstateNotFoundError(FileNotFoundError):
    pass


class EstateDB:
    """Read-only handle onto one estate_NNNN.db. Use as a context manager:

        with EstateDB(estate_path) as estate:
            facturas = estate.obtener_facturas(rfc_emisor="AAAA010101AA1")

    `estate_path` is supplied by the caller at run time (CLI arg, env var,
    config) — never hardcoded here or anywhere upstream of this class.
    """

    def __init__(self, estate_path: str | Path):
        self.path = Path(estate_path)
        if not self.path.exists():
            raise EstateNotFoundError(f"No estate file at {self.path}")
        # Read-only URI connection: a bug or a prompt-injected instruction
        # in an invoice's concepto_text can never turn into a write.
        uri = f"file:{self.path.as_posix()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def __enter__(self) -> "EstateDB":
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._conn.close()

    # -- internal helpers --------------------------------------------

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        row = self._conn.execute(sql, params).fetchone()
        return row

    # -- vendors -------------------------------------------------------

    def obtener_proveedor(self, rfc: str) -> Optional[Vendor]:
        """Busca un proveedor por su RFC exacto. Devuelve None si no existe
        en la tabla vendors de esta estate."""
        row = self._one("SELECT * FROM vendors WHERE rfc = ?", (rfc,))
        return Vendor(**dict(row)) if row else None

    def buscar_proveedores(
        self, nombre_parcial: Optional[str] = None, categoria: Optional[str] = None
    ) -> list[Vendor]:
        """Busca proveedores por coincidencia parcial de nombre y/o por
        categoria exacta (p. ej. 'Consultoria'). Sin filtros, devuelve todos
        los proveedores registrados."""
        clauses, params = [], []
        if nombre_parcial:
            clauses.append("legal_name LIKE ?")
            params.append(f"%{nombre_parcial}%")
        if categoria:
            clauses.append("category = ?")
            params.append(categoria)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM vendors {where} ORDER BY legal_name", tuple(params))
        return [Vendor(**dict(r)) for r in rows]

    # -- employees -------------------------------------------------------

    def obtener_empleado(self, emp_id: str) -> Optional[Employee]:
        """Busca un empleado por su emp_id (formato 'EMP:0001')."""
        row = self._one("SELECT * FROM employees WHERE emp_id = ?", (emp_id,))
        return Employee(**dict(row)) if row else None

    def buscar_empleados(self, nombre_parcial: Optional[str] = None) -> list[Employee]:
        """Busca empleados por coincidencia parcial de nombre. Sin filtro,
        devuelve todos los empleados."""
        if nombre_parcial:
            rows = self._query(
                "SELECT * FROM employees WHERE name LIKE ? ORDER BY name",
                (f"%{nombre_parcial}%",),
            )
        else:
            rows = self._query("SELECT * FROM employees ORDER BY name")
        return [Employee(**dict(r)) for r in rows]

    def empleado_por_clabe(self, clabe: str) -> Optional[Employee]:
        """Busca al empleado dueno de una CLABE bancaria dada, si existe."""
        row = self._one("SELECT * FROM employees WHERE bank_clabe = ?", (clabe,))
        return Employee(**dict(row)) if row else None

    # -- contracts / purchase orders -------------------------------------

    def obtener_contratos(self, rfc_proveedor: Optional[str] = None) -> list[Contract]:
        """Devuelve los contratos de un proveedor (o todos, sin filtro)."""
        if rfc_proveedor:
            rows = self._query(
                "SELECT * FROM contracts WHERE vendor_rfc = ? ORDER BY start_date",
                (rfc_proveedor,),
            )
        else:
            rows = self._query("SELECT * FROM contracts ORDER BY start_date")
        return [Contract(**dict(r)) for r in rows]

    def obtener_ordenes_compra(
        self,
        rfc_proveedor: Optional[str] = None,
        requester: Optional[str] = None,
        approver: Optional[str] = None,
    ) -> list[PurchaseOrder]:
        """Devuelve ordenes de compra filtradas por proveedor, solicitante
        y/o aprobador. Sin filtros, devuelve todas."""
        clauses, params = [], []
        if rfc_proveedor:
            clauses.append("vendor_rfc = ?")
            params.append(rfc_proveedor)
        if requester:
            clauses.append("requester = ?")
            params.append(requester)
        if approver:
            clauses.append("approver = ?")
            params.append(approver)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM purchase_orders {where} ORDER BY date", tuple(params))
        return [PurchaseOrder(**dict(r)) for r in rows]

    # -- invoices ----------------------------------------------------

    def obtener_factura(self, uuid: str) -> Optional[Invoice]:
        """Busca una factura por su UUID (CFDI) exacto."""
        row = self._one("SELECT * FROM invoices WHERE uuid = ?", (uuid,))
        return Invoice(**dict(row)) if row else None

    def obtener_facturas(
        self,
        rfc_emisor: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
        metodo_pago: Optional[str] = None,
    ) -> list[Invoice]:
        """Busca facturas por emisor, receptor, rango de fechas (ISO 8601,
        inclusive) y/o metodo de pago ('PUE' | 'PPD'). Todos los filtros son
        opcionales y se combinan con AND; sin ninguno, devuelve todas las
        facturas de la estate — usalo con filtros para no inundarte."""
        clauses, params = [], []
        if rfc_emisor:
            clauses.append("issuer_rfc = ?")
            params.append(rfc_emisor)
        if rfc_receptor:
            clauses.append("receiver_rfc = ?")
            params.append(rfc_receptor)
        if fecha_inicio:
            clauses.append("issue_date >= ?")
            params.append(fecha_inicio)
        if fecha_fin:
            clauses.append("issue_date <= ?")
            params.append(fecha_fin)
        if metodo_pago:
            clauses.append("metodo_pago = ?")
            params.append(metodo_pago)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM invoices {where} ORDER BY issue_date", tuple(params))
        return [Invoice(**dict(r)) for r in rows]

    # -- ledger ----------------------------------------------------

    def obtener_asientos_contables(
        self,
        invoice_uuid: Optional[str] = None,
        cost_center: Optional[str] = None,
        approver: Optional[str] = None,
    ) -> list[LedgerEntry]:
        """Devuelve asientos del libro mayor, filtrando opcionalmente por
        factura asociada, centro de costo o quien aprobo el asiento."""
        clauses, params = [], []
        if invoice_uuid:
            clauses.append("invoice_uuid = ?")
            params.append(invoice_uuid)
        if cost_center:
            clauses.append("cost_center = ?")
            params.append(cost_center)
        if approver:
            clauses.append("approver = ?")
            params.append(approver)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM ledger {where} ORDER BY date", tuple(params))
        return [LedgerEntry(**dict(r)) for r in rows]

    # -- bank transfers / money tracing --------------------------------

    def obtener_transferencias(
        self,
        clabe: Optional[str] = None,
        direccion: str = "ambas",
        fecha_inicio: Optional[str] = None,
        fecha_fin: Optional[str] = None,
    ) -> list[BankTxn]:
        """Busca transferencias bancarias que involucren una CLABE.
        `direccion` es 'entrante' (to_clabe = clabe), 'saliente'
        (from_clabe = clabe), o 'ambas' (por defecto). Sin `clabe`, filtra
        solo por fecha (o devuelve todas si tampoco hay fechas)."""
        clauses, params = [], []
        if clabe:
            if direccion == "entrante":
                clauses.append("to_clabe = ?")
                params.append(clabe)
            elif direccion == "saliente":
                clauses.append("from_clabe = ?")
                params.append(clabe)
            else:
                clauses.append("(from_clabe = ? OR to_clabe = ?)")
                params.extend([clabe, clabe])
        if fecha_inicio:
            clauses.append("date >= ?")
            params.append(fecha_inicio)
        if fecha_fin:
            clauses.append("date <= ?")
            params.append(fecha_fin)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM bank_txns {where} ORDER BY date", tuple(params))
        return [BankTxn(**dict(r)) for r in rows]

    def obtener_transferencia(self, txn_id: str) -> Optional[BankTxn]:
        """Busca una transferencia bancaria por su txn_id exacto (p. ej. 'BNK-00001')."""
        row = self._one("SELECT * FROM bank_txns WHERE txn_id = ?", (txn_id,))
        return BankTxn(**dict(row)) if row else None

    def trazar_pagos(
        self,
        txn_id: str,
        dias_max_entre_saltos: int = 10,
        profundidad_max: int = 6,
    ) -> list[BankTxn]:
        """Sigue el rastro del dinero a partir de una transferencia: busca
        la siguiente transferencia cuya CLABE de origen sea la CLABE de
        destino de la anterior, dentro de `dias_max_entre_saltos` dias, hasta
        `profundidad_max` saltos o hasta que el rastro se corte o vuelva a
        una CLABE ya visitada (senal de ciclo, que se incluye como ultimo
        salto). Devuelve la cadena ordenada, empezando por txn_id.

        Este es el tool para armar un money_trail de round_tripping o de
        cualquier cadena de transferencias relacionadas — no reconstruyas
        esto a mano leyendo obtener_transferencias() en un loop; usa esto."""
        start = self.obtener_transferencia(txn_id)
        if start is None:
            return []
        trail = [start]
        visited_clabes = {start.from_clabe}
        current = start
        for _ in range(profundidad_max - 1):
            next_hop = self._one(
                """
                SELECT * FROM bank_txns
                WHERE from_clabe = ?
                  AND date >= ?
                  AND date <= date(?, ?)
                  AND txn_id != ?
                ORDER BY date ASC
                LIMIT 1
                """,
                (
                    current.to_clabe,
                    current.date,
                    current.date,
                    f"+{dias_max_entre_saltos} days",
                    current.txn_id,
                ),
            )
            if next_hop is None:
                break
            hop = BankTxn(**dict(next_hop))
            trail.append(hop)
            if hop.to_clabe in visited_clabes:
                break  # cycle closed
            visited_clabes.add(hop.from_clabe)
            current = hop
        return trail

    def resolver_clabe(self, clabe: str, company_clabe: Optional[str] = None) -> ClabeOwner:
        """Identifica a quien pertenece una CLABE dentro de esta estate:
        un proveedor, un empleado, la propia empresa (si se pasa
        `company_clabe`), o 'unknown' si no aparece en ninguna tabla propia
        (tipico de cuentas intermedias / de terceros en un round-trip)."""
        if company_clabe and clabe == company_clabe:
            return ClabeOwner(clabe, "company", "COMPANY", "La empresa auditada")
        row = self._one("SELECT rfc, legal_name FROM vendors WHERE bank_clabe = ?", (clabe,))
        if row:
            return ClabeOwner(clabe, "vendor", row["rfc"], row["legal_name"])
        row = self._one("SELECT emp_id, name FROM employees WHERE bank_clabe = ?", (clabe,))
        if row:
            return ClabeOwner(clabe, "employee", row["emp_id"], row["name"])
        return ClabeOwner(clabe, "unknown", "", "")

    # -- SAT 69-B (efos_list) ----------------------------------------

    def esta_en_lista_69b(self, rfc: str) -> Optional[EfosRecord]:
        """Revisa si un RFC aparece en la lista 69-B (efos_list) de esta
        estate y devuelve su registro, o None si no aparece."""
        row = self._one("SELECT * FROM efos_list WHERE rfc = ?", (rfc,))
        return EfosRecord(**dict(row)) if row else None

    def obtener_lista_69b(self, status: Optional[str] = None) -> list[EfosRecord]:
        """Devuelve la lista 69-B completa de esta estate, opcionalmente
        filtrada por status ('definitivo' | 'presunto')."""
        if status:
            rows = self._query("SELECT * FROM efos_list WHERE status = ?", (status,))
        else:
            rows = self._query("SELECT * FROM efos_list")
        return [EfosRecord(**dict(r)) for r in rows]

    # -- composite / high-level -----------------------------------------

    def perfil_proveedor(self, rfc: str) -> VendorProfile:
        """Vista agregada de un proveedor: si existe, si esta en la lista
        69-B, si tiene contrato, si tiene ordenes de compra, cuantas
        facturas le ha pagado la empresa, el monto total facturado, y
        cuantas de esas facturas no tienen ni PO ni contrato de respaldo.
        Este es normalmente el primer tool a llamar sobre un lead nuevo,
        antes de bajar a facturas o transferencias individuales."""
        vendor = self.obtener_proveedor(rfc)
        efos = self.esta_en_lista_69b(rfc)
        contratos = self.obtener_contratos(rfc)
        pos = self.obtener_ordenes_compra(rfc_proveedor=rfc)
        facturas = self.obtener_facturas(rfc_emisor=rfc)
        # Heuristic at the profile level: no contract AND no PO at all means
        # every invoice from this vendor lacks paper backing. Per-invoice
        # matching (which PO covers which invoice) belongs in src/detectors,
        # not here — this tool answers "should I look closer?", not "prove it".
        sin_respaldo = len(facturas) if (not contratos and not pos) else 0
        return VendorProfile(
            vendor=vendor,
            en_lista_69b=efos,
            tiene_contrato=bool(contratos),
            tiene_ordenes_compra=bool(pos),
            num_facturas=len(facturas),
            monto_total_facturado=round(sum(f.total for f in facturas), 2),
            facturas_sin_po_ni_contrato=sin_respaldo,
        )

    def identificar_empresa(self) -> CompanyProfile:
        """Infiere el RFC y la CLABE de la empresa auditada a partir de los
        propios datos de esta estate — el schema no tiene una tabla
        'company' dedicada, y esto NUNCA se lee del archivo de ground truth
        (que ademas no expone estos campos a esta capa).

        Heuristica: el RFC que aparece con mas frecuencia como
        receiver_rfc entre todas las facturas es la empresa (sus
        proveedores le facturan a ella, y eso domina el conteo frente a las
        pocas facturas de ingreso que ella misma emite). La CLABE que
        aparece con mas frecuencia como from_clabe entre todas las
        transferencias salientes es su cuenta bancaria (paga a docenas de
        proveedores distintos desde la misma cuenta, mientras que una CLABE
        intermedia de un ciclo de lavado solo aparece una vez).

        `confianza_rfc`/`confianza_clabe` es la fraccion de la evidencia
        total que respalda cada valor — util para que quien llame decida
        si confiar en la inferencia sobre una estate muy pequena o atipica."""
        row = self._one(
            "SELECT receiver_rfc, COUNT(*) AS n FROM invoices GROUP BY receiver_rfc ORDER BY n DESC LIMIT 1"
        )
        total_row = self._one("SELECT COUNT(*) AS n FROM invoices")
        total_inv = total_row["n"] if total_row else 0
        rfc = row["receiver_rfc"] if row else ""
        conf_rfc = round((row["n"] / total_inv), 4) if row and total_inv else 0.0

        row2 = self._one(
            "SELECT from_clabe, COUNT(*) AS n FROM bank_txns GROUP BY from_clabe ORDER BY n DESC LIMIT 1"
        )
        total_row2 = self._one("SELECT COUNT(*) AS n FROM bank_txns")
        total_txn = total_row2["n"] if total_row2 else 0
        clabe = row2["from_clabe"] if row2 else ""
        conf_clabe = round((row2["n"] / total_txn), 4) if row2 and total_txn else 0.0

        return CompanyProfile(rfc=rfc, clabe=clabe, confianza_rfc=conf_rfc, confianza_clabe=conf_clabe)

    def existe_registro(self, source_table: str, record_id: str) -> bool:
        """Confirma si un record_id existe en una tabla dada de esta estate.
        Uso previsto: el validator, para rechazar exhibits con ids
        inventados antes de que un Finding se imprima. `source_table` debe
        ser uno de: ledger, invoices, bank_txns, vendors, efos_list,
        purchase_orders, contracts, employees (el mismo enum que
        submission_schema.json)."""
        pk_by_table = {
            "ledger": "entry_id",
            "invoices": "uuid",
            "bank_txns": "txn_id",
            "vendors": "rfc",
            "efos_list": "rfc",
            "purchase_orders": "po_id",
            "contracts": "contract_id",
            "employees": "emp_id",
        }
        pk = pk_by_table.get(source_table)
        if pk is None:
            raise ValueError(f"source_table desconocida: {source_table!r}")
        row = self._one(f"SELECT 1 FROM {source_table} WHERE {pk} = ?", (record_id,))
        return row is not None
