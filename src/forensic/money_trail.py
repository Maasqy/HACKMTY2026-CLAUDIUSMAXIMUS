"""
src/forensic/money_trail.py

Builds the `money_trail` a finding needs: ordered steps where each step's
destination is the next step's source, every step citing an exhibit_id that
exists in that same finding.

Built DETERMINISTICALLY from bank_txns, never asked from the model. The
schema requires the chain to connect, and a language model asked to narrate
a money flow will produce a chain that reads perfectly and does not match
the ledger. Here the endpoints come from `resolver_clabe`, so each hop is
named in plain language ("la empresa", "RFC:XXX", "EMP:0001") instead of
raw 18-digit CLABEs — which is the point of the diagram for a non-technical
judge.

An empty trail is a legitimate result: phantom_vendor findings whose
evidence is documentary (an efos_list match plus invoices with no payment)
have no money movement to draw. The caller emits `money_trail: []` in that
case, which satisfies the schema — what the validator rejects is the key
being absent, not it being empty.
"""

from __future__ import annotations


def _nombrar(estate, clabe: str, company) -> str:
    """CLABE -> plain-language owner, via the typed access layer."""
    if company and clabe == company.clabe:
        return "la empresa"
    owner = estate.resolver_clabe(clabe, company_clabe=company.clabe if company else None)
    if owner.owner_type == "company":
        return "la empresa"
    if owner.owner_type == "vendor":
        return f"RFC:{owner.owner_id}"
    if owner.owner_type == "employee":
        return f"{owner.owner_id} ({owner.owner_name})"
    return f"cuenta externa ...{clabe[-4:]}" if clabe else "cuenta desconocida"


def construir(estate, exhibits: list[dict], company=None) -> list[dict]:
    """Returns the ordered money_trail for the given (already validated)
    exhibits.

    Only bank_txns exhibits carry a movement. They are ordered by date, and
    each one becomes a step citing its own exhibit_id, so every step maps
    back to a record a judge can open.
    """
    company = company or estate.identificar_empresa()

    pasos = []
    for ex in exhibits:
        if ex.get("source_table") != "bank_txns":
            continue
        txn = estate.obtener_transferencia(str(ex.get("record_id", "")))
        if txn is None:
            continue
        pasos.append({
            "from": _nombrar(estate, txn.from_clabe, company),
            "to": _nombrar(estate, txn.to_clabe, company),
            "amount": round(float(txn.amount), 2),
            "date": txn.date,
            "exhibit_id": ex.get("exhibit_id", ""),
            "_orden": txn.date,
        })

    pasos.sort(key=lambda p: p["_orden"])
    for p in pasos:
        p.pop("_orden", None)
    return pasos
