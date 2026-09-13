"""
src/forensic/validator.py — etapa 4 del pipeline.

    SQLite -> CART -> Gemma -> [VALIDATOR: AQUI] -> challenger -> reporting

Deterministic gate between the model's draft and anything that can be
printed as an accusation. Takes the JSON the investigator produced, goes
back to SQLite, and answers one boolean: does this survive?

It exists because a language model can emit a UUID that is perfectly
well-formed and completely invented, a peso_amount that does not add up,
or a confident narrative citing two exhibits when the rule is three. None
of those are caught by reading the text — only by querying the data again.

The track states it plainly: an accusation must validate before it prints.
record_id must exist; peso_amount must reconcile within 2%, summed per
table. Everything here is a rule from src/config.py or from
docs/spec/submission_schema.json — no judgement, no model, no thresholds
invented in this file.

A rejected draft is not discarded: it comes back with the exact reasons,
which become the `reason` of a leads_not_pursued entry. The spec wants
declined leads in the case file body with specific reasons, and "the
validator rejected it because invoice X does not exist" is as specific as
it gets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import (
    AMOUNT_TABLES,
    MAX_NARRATIVE_WORDS,
    MIN_EXHIBITS,
    PESO_TOLERANCE,
    SCHEME_TYPES,
    SOURCE_TABLES,
)

_ENTITY_RE = re.compile(r"^(RFC:[A-ZÑ&0-9]{12,13}|EMP:\d{4})$")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """`ok` is the boolean the pipeline advances on. `motivos` is why not."""
    ok: bool
    motivos: tuple[str, ...] = ()
    peso_declarado: float = 0.0
    peso_reconciliado: float = 0.0
    desviacion_pct: float = 0.0
    exhibits_verificados: int = 0
    exhibits_inexistentes: tuple[str, ...] = field(default=(), compare=False)

    @property
    def resumen(self) -> str:
        if self.ok:
            return (f"validado: {self.exhibits_verificados} exhibits existen, "
                    f"monto reconcilia al {self.desviacion_pct:.2f}%")
        return "; ".join(self.motivos)


def _monto_de(estate, source_table: str, record_id: str) -> float | None:
    """Amount carried by one record, or None if the table carries no amount.

    Only invoices/bank_txns/purchase_orders/contracts have a money column
    (AMOUNT_TABLES). A vendor row or an efos_list row is legitimate evidence
    but contributes 0 to the reconciliation — citing the 69-B listing proves
    the vendor is listed, not that pesos moved.
    """
    col = AMOUNT_TABLES.get(source_table)
    if not col:
        return None
    if source_table == "invoices":
        f = estate.obtener_factura(record_id)
        return float(f.total) if f else None
    if source_table == "bank_txns":
        t = estate.obtener_transferencia(record_id)
        return float(t.amount) if t else None
    if source_table == "purchase_orders":
        for po in estate.obtener_ordenes_compra():
            if po.po_id == record_id:
                return float(po.amount)
        return None
    if source_table == "contracts":
        for c in estate.obtener_contratos():
            if c.contract_id == record_id:
                return float(c.value)
        return None
    return None


def validar(estate, draft) -> ValidationResult:
    """Runs every check against SQLite. Returns ok=True only if all pass."""
    motivos: list[str] = []

    # -- forma: lo que submission_schema.json exige de un finding ---------
    if draft.scheme_type not in SCHEME_TYPES:
        motivos.append(f"scheme_type '{draft.scheme_type}' no esta en el enum oficial")

    if not draft.entities:
        motivos.append("finding sin entities")
    for ent in draft.entities:
        if not _ENTITY_RE.match(str(ent)):
            motivos.append(f"entity '{ent}' no cumple el formato RFC:xxx / EMP:0001")

    palabras = len(draft.narrative.split())
    if palabras == 0:
        motivos.append("narrative vacia")
    elif palabras > MAX_NARRATIVE_WORDS:
        motivos.append(f"narrative de {palabras} palabras, el maximo es {MAX_NARRATIVE_WORDS}")

    if not draft.rule_broken:
        motivos.append("no declara rule_broken")

    if len(draft.exhibits) < MIN_EXHIBITS:
        motivos.append(f"{len(draft.exhibits)} exhibits, el minimo es {MIN_EXHIBITS}")

    # -- fondo: cada record_id tiene que existir de verdad ----------------
    inexistentes: list[str] = []
    verificados = 0
    # POR TABLA, no sumado entre tablas: una factura y la transferencia que la
    # liquido son los mismos pesos vistos dos veces. Sumarlas duplicaria el
    # monto real y peso_amount jamas reconciliaria contra la cifra correcta.
    # Este es exactamente el criterio de validate_format.py (el validador de
    # los jueces) — antes este archivo sumaba entre tablas, lo cual dejaba
    # pasar aqui hallazgos que luego fallaban ese validador oficial.
    por_tabla: dict[str, float] = {}
    for ex in draft.exhibits:
        tabla = str(ex.get("source_table", ""))
        rid = str(ex.get("record_id", ""))
        if tabla not in SOURCE_TABLES:
            motivos.append(f"source_table '{tabla}' no esta en el enum oficial")
            continue
        if not rid:
            motivos.append(f"exhibit en {tabla} sin record_id")
            continue
        if not estate.existe_registro(tabla, rid):
            inexistentes.append(f"{tabla}/{rid}")
            continue
        verificados += 1
        monto = _monto_de(estate, tabla, rid)
        if monto is not None:
            por_tabla[tabla] = por_tabla.get(tabla, 0.0) + monto

    if inexistentes:
        motivos.append(
            f"{len(inexistentes)} record_id citados no existen en la estate "
            f"(alucinacion del modelo): {', '.join(inexistentes[:5])}"
        )

    # -- reconciliacion de pesos -----------------------------------------
    declarado = float(draft.peso_amount or 0.0)
    desviacion = 0.0
    mejor_suma = 0.0
    if declarado <= 0:
        motivos.append("peso_amount es 0 o negativo")
    elif not por_tabla:
        motivos.append("ningun exhibit citado tiene monto con el cual reconciliar")
    else:
        mejor_tabla, mejor_suma = min(por_tabla.items(), key=lambda kv: abs(declarado - kv[1]))
        desviacion = abs(mejor_suma - declarado) / max(declarado, 1.0)
        if desviacion > PESO_TOLERANCE:
            detalle = ", ".join(f"{t}={v:,.2f}" for t, v in sorted(por_tabla.items()))
            motivos.append(
                f"peso_amount {declarado:,.2f} no reconcilia con ninguna tabla citada "
                f"por separado (la mas cercana es {mejor_tabla}={mejor_suma:,.2f}; "
                f"[{detalle}]; desviacion {desviacion * 100:.2f}%, "
                f"tolerancia {PESO_TOLERANCE * 100:.0f}%)"
            )

    return ValidationResult(
        ok=not motivos,
        motivos=tuple(motivos),
        peso_declarado=round(declarado, 2),
        peso_reconciliado=round(mejor_suma, 2),
        desviacion_pct=round(desviacion * 100, 4),
        exhibits_verificados=verificados,
        exhibits_inexistentes=tuple(inexistentes),
    )
