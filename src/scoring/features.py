"""
src/scoring/features.py

Recomputes, using ONLY src.tools.EstateDB — never raw SQL, never pandas over
the .db file directly — the same named features ml/build_features.py
computes offline for training. This is the LIVE, per-entity equivalent: it
produces a feature dict shaped like one row of ml/features_train.csv (minus
estate_seed/rfc, minus scheme_type/es_fraude/situacion_sat, which are
labels, not features).

Like ml/build_features.py, this computes features for an ENTITY — which may
be a vendor (purchase-side features), a client (sales-side features), or
both — not a vendor alone. That is required for the primary scheme_type
model: revenue_inflation's accused entity is a client (an invoice
receiver_rfc, never inserted into `vendors`), so a vendor-only feature
function makes that scheme structurally undetectable regardless of model
quality. See ml/build_features.py's module docstring for the full
rationale.

This file may differ from ml/build_features.py in implementation (it goes
through the typed access layer instead of pandas/sqlite3 directly, since
this code runs as part of the agent under investigation, same as
src/detectors), but the feature NAMES and semantics must match what
modelo_cart_scheme_type.pkl / modelo_cart_situacion_sat.pkl were trained
on, or predictions are meaningless.
"""

from __future__ import annotations

from datetime import date


GENERIC_CONCEPT_WORDS = ("diversos", "diversas", "varios", "varias", "generales", "general")
PO_THRESHOLD = 50000.0
PO_THRESHOLD_BAND = 5000.0


def _dias_entre(a: str, b: str) -> float:
    try:
        return float((date.fromisoformat(b) - date.fromisoformat(a)).days)
    except (ValueError, TypeError):
        return float("nan")


def construir_features_entidad(estate, rfc: str, company=None) -> dict:
    """Construye el vector de features de una entidad (proveedor, cliente,
    o ambos), usando solo src.tools.EstateDB — el mismo bridge que usa el
    resto del agente. Este dict se le pasa directo a
    src.scoring.model.predict_scheme_type() / predict_situacion().

    `company` es un CompanyProfile ya resuelto (estate.identificar_empresa())
    — se acepta como parametro para no recalcularlo por cada entidad al
    generar leads para toda la estate."""
    if company is None:
        company = estate.identificar_empresa()

    vendor = estate.obtener_proveedor(rfc)
    es_proveedor = vendor is not None

    # ---- purchase-side (vendor) features ----
    facturas = estate.obtener_facturas(rfc_emisor=rfc) if es_proveedor else []
    pos = estate.obtener_ordenes_compra(rfc_proveedor=rfc) if es_proveedor else []
    contratos = estate.obtener_contratos(rfc_proveedor=rfc) if es_proveedor else []
    empleados = estate.buscar_empleados()

    n_inv = len(facturas)
    montos = [f.total for f in facturas]
    monto_total = round(sum(montos), 2) if montos else 0.0
    monto_prom = round(monto_total / n_inv, 2) if n_inv else 0.0
    monto_max = round(max(montos), 2) if montos else 0.0
    if n_inv:
        media = monto_total / n_inv
        monto_std = round((sum((m - media) ** 2 for m in montos) / n_inv) ** 0.5, 2)
    else:
        monto_std = 0.0
    pct_ppd = round(sum(1 for f in facturas if f.metodo_pago == "PPD") / n_inv, 4) if n_inv else 0.0
    n_formas_pago = len({f.forma_pago for f in facturas})

    n_po = len(pos)
    pct_mismo_req_apr = round(sum(1 for p in pos if p.requester == p.approver) / n_po, 4) if n_po else 0.0
    pct_bajo_umbral = (
        round(sum(1 for p in pos if PO_THRESHOLD - PO_THRESHOLD_BAND <= p.amount < PO_THRESHOLD) / n_po, 4)
        if n_po else 0.0
    )

    dias_antiguedad = float("nan")
    if es_proveedor and n_inv:
        primera = min(f.issue_date for f in facturas)
        dias_antiguedad = _dias_entre(vendor.registered_date, primera)

    generic_hits = sum(1 for f in facturas if any(w in f.concepto_text.lower() for w in GENERIC_CONCEPT_WORDS))
    pct_concepto_generico = round(generic_hits / n_inv, 4) if n_inv else 0.0

    entrantes_vendor = (
        estate.obtener_transferencias(clabe=vendor.bank_clabe, direccion="entrante") if es_proveedor else []
    )
    n_pagadas = sum(
        1 for f in facturas if any(abs(t.amount - f.total) <= 0.01 * max(f.total, 1) for t in entrantes_vendor)
    )
    pct_sin_pago = round(1 - n_pagadas / n_inv, 4) if n_inv else 0.0
    n_transferencias = len(entrantes_vendor)
    monto_transferido = round(sum(t.amount for t in entrantes_vendor), 2) if entrantes_vendor else 0.0

    invoice_uuids = {f.uuid for f in facturas}
    monto_ledger = round(
        sum(e.debit for uid in invoice_uuids for e in estate.obtener_asientos_contables(invoice_uuid=uid)), 2
    ) if invoice_uuids else 0.0

    employee_clabes = {e.bank_clabe for e in empleados}
    employee_institutions = {c[:3] for c in employee_clabes if len(c) >= 3}
    clabe_identica = int(vendor.bank_clabe in employee_clabes) if es_proveedor else 0
    institucion_igual = (
        int(vendor.bank_clabe[:3] in employee_institutions) if es_proveedor and len(vendor.bank_clabe) >= 3 else 0
    )

    efos = estate.esta_en_lista_69b(rfc)
    en_69b = int(efos is not None)
    es_definitivo = int(efos is not None and efos.status == "definitivo")

    # ---- sales-side (client) features ----
    ventas = estate.obtener_facturas(rfc_emisor=company.rfc, rfc_receptor=rfc) if company.rfc else []
    es_cliente = len(ventas) > 0
    n_inv_venta = len(ventas)
    monto_total_venta = round(sum(v.total for v in ventas), 2) if ventas else 0.0
    monto_prom_venta = round(monto_total_venta / n_inv_venta, 2) if n_inv_venta else 0.0

    entrantes_empresa = (
        estate.obtener_transferencias(clabe=company.clabe, direccion="entrante") if company.clabe else []
    )
    n_cobradas = sum(
        1 for v in ventas if any(abs(t.amount - v.total) <= 0.01 * max(v.total, 1) for t in entrantes_empresa)
    )
    pct_venta_sin_cobro = round(1 - n_cobradas / n_inv_venta, 4) if n_inv_venta else 0.0

    dias_a_cierre_periodo_venta = float("nan")
    if n_inv_venta:
        todos_los_ingresos = estate.obtener_facturas(rfc_emisor=company.rfc) if company.rfc else []
        if todos_los_ingresos:
            fecha_max_ingreso = max(date.fromisoformat(f.issue_date) for f in todos_los_ingresos)
            ultima_venta = max(date.fromisoformat(v.issue_date) for v in ventas)
            dias_a_cierre_periodo_venta = float((fecha_max_ingreso - ultima_venta).days)

    return {
        "es_proveedor": int(es_proveedor),
        "es_cliente": int(es_cliente),
        "categoria": vendor.category if es_proveedor else "cliente",
        "num_facturas": n_inv,
        "monto_total_facturado": monto_total,
        "monto_promedio_factura": monto_prom,
        "monto_max_factura": monto_max,
        "monto_std_factura": monto_std,
        "pct_facturas_ppd": pct_ppd,
        "num_formas_pago_distintas": n_formas_pago,
        "tiene_contrato": int(bool(contratos)),
        "num_contratos": len(contratos),
        "tiene_orden_compra": int(n_po > 0),
        "num_ordenes_compra": n_po,
        "pct_po_mismo_requester_approver": pct_mismo_req_apr,
        "pct_po_justo_bajo_umbral_50k": pct_bajo_umbral,
        "en_lista_69b": en_69b,
        "es_69b_definitivo": es_definitivo,
        "dias_antiguedad_al_facturar": dias_antiguedad,
        "num_transferencias_recibidas": n_transferencias,
        "monto_total_transferido": monto_transferido,
        "pct_facturas_sin_pago_rastreable": pct_sin_pago,
        "pct_concepto_generico": pct_concepto_generico,
        "clabe_identica_a_empleado": clabe_identica,
        "misma_institucion_bancaria_que_empleado": institucion_igual,
        "monto_total_en_ledger": monto_ledger,
        "num_facturas_venta": n_inv_venta,
        "monto_total_venta": monto_total_venta,
        "monto_promedio_venta": monto_prom_venta,
        "pct_facturas_venta_sin_cobro": pct_venta_sin_cobro,
        "dias_a_cierre_periodo_venta": dias_a_cierre_periodo_venta,
    }


def construir_features_proveedor(estate, rfc: str) -> dict:
    """Alias de compatibilidad — antes esta era la unica funcion (solo lado
    proveedor). Preferir construir_features_entidad, que tambien cubre el
    lado cliente (necesario para revenue_inflation)."""
    return construir_features_entidad(estate, rfc)
