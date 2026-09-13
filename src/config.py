"""Constantes de negocio del sistema forense.

Viven en codigo, nunca en un prompt. La especificacion de Infosys lo exige
explicitamente y un juez puede pedir abrir este archivo.
"""

# Limite de autorizacion de compra. Arriba de esto se requiere segunda firma.
APPROVAL_LIMIT_MXN = 50_000.00

# Tolerancia de reconciliacion entre peso_amount y la suma de exhibits citados.
PESO_TOLERANCE = 0.02

# Minimo de exhibits por acusacion.
MIN_EXHIBITS = 3

# Maximo de palabras de la narrativa de un finding.
MAX_NARRATIVE_WORDS = 150

# Tipos de esquema. Enum cerrado por la especificacion oficial.
SCHEME_TYPES = ("phantom_vendor", "kickback", "round_tripping",
                "threshold_splitting", "revenue_inflation")

# Tablas del estate que llevan monto, usadas para reconciliar.
AMOUNT_TABLES = {"invoices": "total", "bank_txns": "amount",
                 "purchase_orders": "amount", "contracts": "value"}

# Limites del loop de investigacion.
MAX_STEPS_PER_RUN = 60
MAX_LLM_CALLS_PER_RUN = 120

# Ventana de reconciliacion para payment_without_invoice: se suman las facturas
# emitidas por el vendor en el mismo mes calendario del bank_txn.
RECONCILIATION_WINDOW_MONTHS = 1

# Estatus de efos_list que la ley SAT considera acusable en si mismo.
EFOS_DEFINITIVO = "definitivo"

# rule_broken con estas palabras se rechaza: describen un patron estadistico,
# no una regla concreta. Los jueces exigen la regla, no la senal.
STATISTICAL_RULE_BLOCKLIST = frozenset({
    "outlier", "anomalia", "anomalía", "z-score", "z score",
    "desviacion", "desviación", "cluster", "score",
})
