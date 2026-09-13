"""round_tripping: los recursos regresan al originante sin sustancia economica.

Senal (topologica):
  - Ciclo en el grafo dirigido de bank_txns que sale del CLABE de la empresa,
    pasa por ROUNDTRIP_MIN_HOPS-1 a ROUNDTRIP_MAX_HOPS-1 intermediarios, y
    vuelve al CLABE de la empresa.
  - Longitud del ciclo: ROUNDTRIP_MIN_HOPS a ROUNDTRIP_MAX_HOPS saltos.
  - Ventana temporal: (last.date - first.date).days <= ROUNDTRIP_WINDOW_DAYS.
  - Los CLABEs intermedios son distintos y != CLABE de la empresa.
  - El primer intermediario es un vendor registrado (contraparte acusable).
  - Retorno positivo minimo: last.amount >= first.amount * ROUNDTRIP_MIN_RETURN_PCT.
  - Tolerancia de monto: |last.amount - first.amount| / first.amount
    <= ROUNDTRIP_AMOUNT_TOLERANCE (laxa: los ciclos AMLSim decaen ~95%).

Implementacion: DFS con profundidad limitada sobre el grafo cargado en memoria.

peso_amount = suma de todos los amounts del ciclo (el volumen total simulado).
La reconciliacion contra la tabla bank_txns es exacta porque se citan como
exhibits todos los bank_txns del ciclo.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.config import (
    ROUNDTRIP_AMOUNT_TOLERANCE,
    ROUNDTRIP_MAX_HOPS,
    ROUNDTRIP_MIN_HOPS,
    ROUNDTRIP_MIN_RETURN_PCT,
    ROUNDTRIP_WINDOW_DAYS,
)
from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


DETECTOR_ID = "round_tripping"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    all_txns = db.obtener_transferencias()
    graph: dict[str, list] = defaultdict(list)
    for t in all_txns:
        if _parse(t.date) is None:
            continue
        graph[t.from_clabe].append(t)
    for clabe in graph:
        graph[clabe].sort(key=lambda x: (x.date, x.txn_id))

    cycles: list[list] = []
    sigs: set[tuple[str, ...]] = set()
    seeds = graph.get(company.clabe, [])
    for seed in seeds:
        if seed.to_clabe == company.clabe:
            continue
        _extend(
            path=[seed],
            visited={seed.to_clabe},
            pos=seed.to_clabe,
            first_date=_parse(seed.date),
            graph=graph,
            company_clabe=company.clabe,
            cycles=cycles,
            sigs=sigs,
        )

    leads: list[Lead] = []
    dedup_entity: set[str] = set()
    for cycle in sorted(cycles, key=lambda c: (c[0].date, c[0].txn_id, len(c))):
        first = cycle[0]
        last = cycle[-1]
        intermediates = [t.to_clabe for t in cycle[:-1]]
        primary_clabe = intermediates[0]
        owner = db.resolver_clabe(primary_clabe)
        # Solo aceptar vendor como primer intermediario. Un empleado receptor
        # de un flujo circular es raro en la practica y aumenta falsas.
        if owner.owner_type != "vendor":
            continue
        entity = f"RFC:{owner.owner_id}"

        if entity in dedup_entity:
            continue
        dedup_entity.add(entity)

        span = (_parse(last.date) - _parse(first.date)).days
        delta_pct = abs(last.amount - first.amount) / max(first.amount, 1.0)
        route = " -> ".join(
            [_short(first.from_clabe)] + [_short(c) for c in intermediates]
            + [_short(last.to_clabe)]
        )
        reason = (
            f"Ciclo de {len(cycle)} saltos en {span} dias: la empresa envio "
            f"${first.amount:,.2f} MXN el {first.date} y recibio "
            f"${last.amount:,.2f} MXN de vuelta el {last.date} "
            f"(delta {delta_pct * 100:.1f}%). Ruta: {route}."
        )
        records = tuple(("bank_txns", t.txn_id) for t in cycle)
        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=entity,
            signal="roundtrip_return_to_company",
            reason=reason,
            suggested_records=records,
            monto_estimado=round(sum(t.amount for t in cycle), 2),
            detector_context=(
                ("cycle_length", str(len(cycle))),
                ("first_txn", first.txn_id),
                ("last_txn", last.txn_id),
                ("first_amount", f"{first.amount:.2f}"),
                ("last_amount", f"{last.amount:.2f}"),
                ("delta_pct", f"{delta_pct:.4f}"),
                ("span_days", str(span)),
                ("primary_clabe", primary_clabe),
                ("cycle_txns", ",".join(t.txn_id for t in cycle)),
            ),
        ))
    return leads


def _extend(path, visited, pos, first_date, graph, company_clabe, cycles, sigs):
    if len(path) >= ROUNDTRIP_MAX_HOPS:
        return
    last_date = _parse(path[-1].date)
    for nxt in graph.get(pos, []):
        nxt_date = _parse(nxt.date)
        if nxt_date is None or nxt_date < last_date:
            continue
        if (nxt_date - first_date).days > ROUNDTRIP_WINDOW_DAYS:
            break
        if nxt.txn_id == path[-1].txn_id:
            continue
        if nxt.to_clabe == company_clabe:
            first_amt = path[0].amount
            if first_amt <= 0 or nxt.amount <= 0:
                continue
            cycle_len = len(path) + 1
            if cycle_len < ROUNDTRIP_MIN_HOPS:
                continue
            return_ratio = nxt.amount / first_amt
            if return_ratio < ROUNDTRIP_MIN_RETURN_PCT:
                continue
            delta = abs(nxt.amount - first_amt) / first_amt
            if delta <= ROUNDTRIP_AMOUNT_TOLERANCE:
                closed = path + [nxt]
                sig = tuple(t.txn_id for t in closed)
                if sig not in sigs:
                    sigs.add(sig)
                    cycles.append(closed)
            continue
        if nxt.to_clabe in visited:
            continue
        visited.add(nxt.to_clabe)
        path.append(nxt)
        _extend(path, visited, nxt.to_clabe, first_date,
                graph, company_clabe, cycles, sigs)
        path.pop()
        visited.discard(nxt.to_clabe)


def _short(clabe: str) -> str:
    if not clabe:
        return "?"
    return f"{clabe[:4]}...{clabe[-4:]}" if len(clabe) > 12 else clabe


def _parse(s: str):
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
