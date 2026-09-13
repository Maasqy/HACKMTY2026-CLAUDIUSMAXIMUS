"""
src/forensic/ — etapa 3 del pipeline: SQLite -> CART -> [Gemma] -> validator -> challenger.

El investigador toma una hipotesis (Lead) y la verifica contra los datos
reales con las herramientas tipadas de src.tools. Devuelve un FindingDraft,
nunca un Finding: la acusacion solo existe despues de que el validador
deterministico confirme cada record_id y reconcilie el monto.

Nada aqui importa eval/ ni referencia el ground truth.
"""

from .client import LLMClient, LLMUnavailableError, LLMUsage
from .investigator import FindingDraft, investigar_lead

__all__ = ["LLMClient", "LLMUsage", "LLMUnavailableError", "FindingDraft", "investigar_lead"]
