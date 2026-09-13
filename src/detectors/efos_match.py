"""efos_match: proveedores que aparecen en efos_list y tienen facturas emitidas.

El detector produce leads. La decision de acusar o no queda en el promoter,
que aplica una regla adicional: la publicacion en efos_list debe ser anterior
a la fecha de la operacion. Un proveedor publicado en 69-B despues de facturar
no era conocido como EFOS en ese momento y no se acusa.
"""

from __future__ import annotations

from src.detectors.base import Lead
from src.forensic.company import CompanyIdentity
from src.tools.estate_access import EstateDB


DETECTOR_ID = "efos_match"


def find_leads(db: EstateDB, company: CompanyIdentity) -> list[Lead]:
    leads: list[Lead] = []
    for efos in sorted(db.obtener_lista_69b(), key=lambda e: e.rfc):
        facturas = [
            f for f in db.obtener_facturas(rfc_emisor=efos.rfc)
            if f.receiver_rfc == company.rfc
        ]
        if not facturas:
            continue

        vendor = db.obtener_proveedor(efos.rfc)
        bank_txns = []
        if vendor is not None and vendor.bank_clabe:
            bank_txns = [
                b for b in db.obtener_transferencias(
                    clabe=vendor.bank_clabe, direccion="entrante"
                )
                if b.from_clabe == company.clabe
            ]

        records: list[tuple[str, str]] = [("efos_list", efos.rfc)]
        for f in sorted(facturas, key=lambda x: x.uuid):
            records.append(("invoices", f.uuid))
        for b in sorted(bank_txns, key=lambda x: x.txn_id):
            records.append(("bank_txns", b.txn_id))

        monto = round(sum(f.total for f in facturas), 2)
        legal = vendor.legal_name if vendor is not None else efos.legal_name
        reason = (
            f"El proveedor {efos.rfc} ({legal}) aparece en la lista 69-B con "
            f"estatus {efos.status} publicado el {efos.publication_date}, y emitio "
            f"{len(facturas)} factura(s) a la empresa por un total de "
            f"${monto:,.2f} MXN."
        )
        leads.append(Lead(
            detector_id=DETECTOR_ID,
            entity=f"RFC:{efos.rfc}",
            signal="efos_69b_match",
            reason=reason,
            suggested_records=tuple(records),
            monto_estimado=monto,
            detector_context=(
                ("efos_status", efos.status),
                ("publication_date", efos.publication_date or ""),
                ("legal_name", legal or ""),
                ("num_facturas", str(len(facturas))),
                ("num_bank_txns", str(len(bank_txns))),
            ),
        ))
    return leads
