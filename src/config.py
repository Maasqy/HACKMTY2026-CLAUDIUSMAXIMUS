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

# Nombres de tabla validos para un exhibit. Enum cerrado por
# docs/spec/submission_schema.json — deliberadamente en ingles, los mismos
# nombres literales de las tablas SQL. Gemma, trabajando en espanol, un dia
# citó "transferencias" en vez de "bank_txns": no invento el dato, tradujo
# el nombre de la tabla, y el validador (correctamente) lo rechazo. Vive
# aqui, un solo lugar, para que prompts.py pueda listarlo explicito en el
# prompt y validator.py siga verificando contra el mismo enum.
SOURCE_TABLES = ("ledger", "invoices", "bank_txns", "vendors", "efos_list",
                 "purchase_orders", "contracts", "employees")

# Tablas del estate que llevan monto, usadas para reconciliar.
AMOUNT_TABLES = {"invoices": "total", "bank_txns": "amount",
                 "purchase_orders": "amount", "contracts": "value"}

# Limites del loop de investigacion.
MAX_STEPS_PER_RUN = 60
MAX_LLM_CALLS_PER_RUN = 120

# --- LLM (etapa 3 investigator y etapa 5 challenger) -----------------------
# El modelo corre local (Ollama) para que la corrida replique sin red, que es
# requisito de la spec. Todo esto vive en codigo, no en un prompt.
# El tag tiene que ser EXACTAMENTE el que imprime `ollama list`: ollama no
# resuelve nombres parecidos, y un tag que no existe falla en la primera
# llamada, no al arrancar. Se puede sobreescribir por entorno
# (FORENSIC_LLM_MODEL=otro:tag python3 -m src.run ...) para comparar modelos
# sin editar codigo; el valor de aqui es el que corre si nadie dice otra cosa.
# `bash scripts/setup_llm.sh --check` compara este valor contra lo que hay
# instalado y, si no coincide, imprime los tags reales de tu maquina.
LLM_MODEL = os.environ.get("FORENSIC_LLM_MODEL", "gemma3:12b")
LLM_BASE_URL = os.environ.get("FORENSIC_LLM_BASE_URL", "http://localhost:11434")
LLM_SEED = 7                      # fijo: "same seed -> same case file"
LLM_TIMEOUT_S = 120.0
# Ventana de contexto pedida a Ollama en CADA llamada. Sin esto, Ollama usa
# su default (4096, confirmado con `ollama ps` en la maquina de prueba) y un
# lead de varios turnos de tool-calling lo llena: prompt de sistema + catalogo
# de herramientas + resultados de herramientas de hasta 6000 caracteres cada
# uno agotan el espacio, y al modelo no le queda presupuesto para terminar de
# escribir su conclusion — la respuesta se corta a la mitad del JSON (se vio
# literal en .llm_cache/: "...record_" y nada mas). 8192 da margen para un
# loop tipico de 5-7 turnos sin gastar VRAM de mas.
LLM_NUM_CTX = int(os.environ.get("FORENSIC_LLM_NUM_CTX", "8192"))

# Costo imputado por 1k tokens. Un modelo local no factura por token, pero la
# spec pide un numero de MXN y "0.00 porque corre en nuestra laptop" no dice
# nada sobre si el enfoque escala. Esta tarifa es la referencia de un modelo
# hospedado de tamano equivalente, para que la cifra sea comparable.
MXN_PER_1K_TOKENS = 0.004
