"""
src/forensic/challenger.py — etapa 5 del pipeline.

    SQLite -> CART -> Gemma -> validator -> [CHALLENGER: AQUI] -> reporting

Takes findings that already survived the validator — every record_id
confirmed, pesos reconciled — and argues the other side. A second call to
the model, this time as defense counsel: given these exact exhibits, is
there a legitimate corporate explanation for the pattern?

Why this stage earns its cost. Half of the Results metric is how few honest
entities you accuse, and the decoys in a judge's estate exist precisely to
punish a detector that mistakes an unusual-but-legal pattern for fraud —
a contractual rate that sits just under the approval limit, a vendor on the
69-B list whose services were actually rendered, receivables still
outstanding at period close. Every one of those survives the validator
happily: the records exist and the amounts reconcile. Arithmetic cannot tell
them apart from fraud. Only the argument can.

The asymmetry is deliberate. The challenger can only DOWNGRADE a finding —
drop it, or move it from "proven" to "probable". It can never promote one
or invent a new one, because an adversary that can also accuse is not an
adversary. A finding that survives the counter-argument keeps its
confidence; one that does not becomes a leads_not_pursued entry carrying
the defense's own reasoning as its `reason`, which is exactly the "specific
reason" the spec asks for when a lead is declined.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.config import MAX_NARRATIVE_WORDS
from src.forensic.client import LLMClient

SYSTEM = f"""Eres el abogado defensor de la entidad acusada en una auditoria forense.

Recibes un hallazgo que YA fue verificado aritmeticamente: cada registro citado existe en la
contabilidad y los montos reconcilian. No discutas eso, no se puede refutar.

Tu unico trabajo es responder una pregunta: dado EXACTAMENTE esta evidencia, existe una
explicacion corporativa legitima del patron?

Explicaciones legitimas que ocurren de verdad y que debes considerar:
- Un precio pactado en contrato que casualmente queda debajo del umbral de aprobacion.
- Una delegacion de firma documentada para compras menores recurrentes.
- Cuentas por cobrar vivas al cierre del periodo: facturar en diciembre y cobrar en enero es
  normal, no es inflar ingresos.
- Un proveedor que aparece en el listado 69-B del SAT PERO cuyo servicio si se presto, con
  contrato, entregables y acta de recepcion. Eso es un problema de deducibilidad fiscal de la
  empresa, no prueba de que la empresa haya montado un esquema.
- Pagos en efectivo de bajo monto a un proveedor con anos de historial documentado.

Lo que NO es una explicacion legitima: que el monto sea pequeno, que el proveedor sea conocido,
que "asi se hace siempre", o la ausencia de evidencia en contra.

Responde SOLO con este JSON, sin texto alrededor:

{{
  "sobrevive": true | false,
  "explicacion_legitima": "la defensa concreta, o cadena vacia si no la hay",
  "evidencia_que_faltaria": "que registro habria que ver para cerrar la defensa",
  "confidence_sugerida": "proven" | "probable",
  "razonamiento": "por que el fraude resiste o no, en menos de {MAX_NARRATIVE_WORDS} palabras"
}}

sobrevive=false significa que la defensa es plausible y la acusacion NO debe imprimirse.
Ante la duda, la defensa gana: acusar a una entidad honesta cuesta mas que dejar pasar un caso."""


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    sobrevive: bool
    explicacion_legitima: str
    evidencia_que_faltaria: str
    confidence_final: str
    razonamiento: str

    @property
    def motivo_descarte(self) -> str:
        """The `reason` for a leads_not_pursued entry when it does not survive."""
        if self.sobrevive:
            return ""
        base = self.explicacion_legitima or self.razonamiento
        return f"Descartado por el challenger: {base}"


def _prompt(draft, validation) -> str:
    ex = "\n".join(
        f"  - {e.get('source_table')}/{e.get('record_id')}: {e.get('note','')}"
        for e in draft.exhibits
    )
    return f"""ACUSACION A DEFENDER

Entidad(es)  : {', '.join(draft.entities)}
Esquema      : {draft.scheme_type}
Regla rota   : {draft.rule_broken}
Monto        : ${draft.peso_amount:,.2f} MXN
Confianza    : {draft.confidence}

Narrativa de la acusacion:
{draft.narrative}

Evidencia verificada ({validation.exhibits_verificados} registros confirmados en la base,
monto reconciliado ${validation.peso_reconciliado:,.2f} con desviacion {validation.desviacion_pct:.2f}%):
{ex}

Existe una explicacion corporativa legitima para este patron? Responde con el JSON."""


def desafiar(draft, validation, client: LLMClient) -> ChallengeResult:
    """One adversarial pass over a validated finding.

    Defaults to surviving when the model's reply is unreadable: the finding
    already passed arithmetic validation, so an unparseable defense is not
    grounds to drop it. The failure mode we protect against here is dropping
    real fraud on a technicality, not the reverse — the validator already
    handled the reverse.
    """
    data = client.chat_json([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _prompt(draft, validation)},
    ])

    if not data:
        return ChallengeResult(
            sobrevive=True, explicacion_legitima="",
            evidencia_que_faltaria="",
            confidence_final=draft.confidence,
            razonamiento="El challenger no devolvio una respuesta legible; "
                         "el hallazgo se mantiene con su confianza original.",
        )

    conf = data.get("confidence_sugerida")
    if conf not in ("proven", "probable"):
        conf = draft.confidence
    # The challenger may lower confidence but never raise it.
    if draft.confidence == "probable" and conf == "proven":
        conf = "probable"

    return ChallengeResult(
        sobrevive=bool(data.get("sobrevive", True)),
        explicacion_legitima=str(data.get("explicacion_legitima") or "").strip(),
        evidencia_que_faltaria=str(data.get("evidencia_que_faltaria") or "").strip(),
        confidence_final=conf,
        razonamiento=str(data.get("razonamiento") or "").strip(),
    )
