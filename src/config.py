"""Constantes de negocio del sistema forense.

Viven en codigo, nunca en un prompt. La especificacion de Infosys lo exige
explicitamente y un juez puede pedir abrir este archivo.
"""

import os

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

# --- LLM (etapa 3 investigator y etapa 5 challenger) -----------------------
# El modelo corre local (Ollama) para que la corrida replique sin red, que es
# requisito de la spec. Todo esto vive en codigo, no en un prompt.
# El tag es el que responde `ollama list`. Se puede sobreescribir por entorno
# (FORENSIC_LLM_MODEL=gemma3:12b python3 -m src.run ...) para comparar modelos
# sin editar codigo; el valor de aqui es el que corre si nadie dice otra cosa.
LLM_MODEL = os.environ.get("FORENSIC_LLM_MODEL", "gemma3:12b")
LLM_BASE_URL = os.environ.get("FORENSIC_LLM_BASE_URL", "http://localhost:11434")
LLM_SEED = 7                      # fijo: "same seed -> same case file"
LLM_TIMEOUT_S = 120.0

# Costo imputado por 1k tokens. Un modelo local no factura por token, pero la
# spec pide un numero de MXN y "0.00 porque corre en nuestra laptop" no dice
# nada sobre si el enfoque escala. Esta tarifa es la referencia de un modelo
# hospedado de tamano equivalente, para que la cifra sea comparable.
MXN_PER_1K_TOKENS = 0.004
