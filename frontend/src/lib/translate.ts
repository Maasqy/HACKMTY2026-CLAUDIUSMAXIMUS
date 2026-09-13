// Runtime Spanish → English translation for pipeline output strings.
// The Python side emits narrative/reason strings in Spanish; the UI is
// English-only. Pattern replacements are ordered longest-first so
// multi-word phrases match before shorter substrings.

type Replacement = [RegExp, string | ((match: string, ...groups: string[]) => string)];

const REPLACEMENTS: Replacement[] = [
  // Full phrases (must run before individual words)
  [/est[aá] publicado por el SAT en la lista 69-B/gi, "is on the SAT 69-B shell-taxpayer list"],
  [/aparece en la lista 69-B/gi, "appears on the SAT 69-B list"],
  [/el SAT resolvi[oó] a favor del contribuyente/gi, "SAT resolved in favor of the taxpayer"],
  [/el listado 69-B distingue sospechoso de exonerado y no se acusa a un exonerado/gi, "the 69-B list distinguishes suspects from cleared taxpayers — we do not accuse a cleared vendor"],
  [/presunto sin resoluci[oó]n; la presunci[oó]n admite prueba en contrario\. Se mantiene como lead pero sin acusaci[oó]n/gi, "presumed status with no resolution; the presumption is rebuttable. Kept as a lead, no accusation"],
  [/no tiene promoter en el baseline; queda como lead con la se[nñ]al para revisi[oó]n manual/gi, "has no promoter in the baseline; kept as a lead for manual review"],
  [/el detector '([^']+)' no tiene promoter en el baseline/gi, "detector '$1' has no promoter in the baseline"],
  [/Cerrado por (\w+):/gi, "Closed by $1:"],
  [/Materialidad no acreditada/gi, "Materiality not proven"],
  [/no existe contrato registrado para el proveedor/gi, "no contract on file for the vendor"],
  [/no existe orden de compra registrada para el proveedor/gi, "no purchase order on file for the vendor"],
  [/algunas operaciones son posteriores al listado del ([\d-]+)/gi, "some operations post-date the listing on $1"],
  [/el efecto del 69-B tambi[eé]n alcanza retroactivamente a las anteriores/gi, "the 69-B effect also reaches prior operations retroactively"],
  [/operaciones amparadas por CFDI de contribuyente en listado 69-B definitivo no producen ni produjeron efectos fiscales/gi, "operations supported by CFDIs from a definitively-listed 69-B taxpayer produce no fiscal effect, past or present"],
  [/efecto retroactivo/gi, "retroactive effect"],
  [/El l[ií]mite de autorizaci[oó]n interno se elude al fraccionar lo que econ[oó]micamente es una sola compra en pedazos independientes/gi, "The internal approval limit is evaded by splitting what is economically a single purchase into independent pieces"],
  [/Pol[ií]tica interna de autorizaci[oó]n: toda compra superior a \$([\d,]+) MXN requiere segunda firma \(umbral en ([^)]+)\)/gi, "Internal approval policy: every purchase above \\$$1 MXN requires a second signature (threshold in $2)"],
  [/publicado el/gi, "published on"],
  [/Publicado en la lista 69-B con estatus (\w+) el ([\d-]+)/gi, "Listed on the 69-B list with status $1 on $2"],

  // Short phrases
  [/con estatus definitivo/gi, "with definitive status"],
  [/con estatus favorable/gi, "with favorable status"],
  [/con estatus desvirtuado/gi, "with disproven status"],
  [/con estatus presunto/gi, "with presumed status"],
  [/estatus definitivo/gi, "definitive status"],
  [/estatus favorable/gi, "favorable status"],
  [/estatus desvirtuado/gi, "disproven status"],
  [/estatus presunto/gi, "presumed status"],

  // Sentence templates
  [/La empresa recibi[oó] (\d+) factura\(s\) desde ([\d-]+) y pag[oó] \$([\d,.]+) MXN en (\d+) transferencia\(s\)/gi, "The company received $1 invoice(s) from $2 onward and paid \\$$3 MXN in $4 transfer(s)"],
  [/El proveedor (\S+) \(([^)]+)\) aparece en la lista 69-B con estatus (\w+) publicado el ([\d-]+), y emiti[oó] (\d+) factura\(s\) a la empresa por un total de \$([\d,.]+) MXN\./gi, "Vendor $1 ($2) is on the 69-B list with status $3 published on $4 and issued $5 invoice(s) to the company for a total of \\$$6 MXN."],
  [/El proveedor (\S+) \(([^)]+)\) recibi[oó]/gi, "Vendor $1 ($2) received"],
  [/El proveedor (\S+) \(([^)]+)\) esta publicado por el SAT/gi, "Vendor $1 ($2) is listed by SAT"],
  [/El proveedor/gi, "The vendor"],
  [/el proveedor/gi, "the vendor"],
  [/aprobada por/gi, "approved by"],
  [/firmadas por/gi, "signed by"],
  [/En (\d{4}-\d{2}) la empresa pag[oó] \$([\d,.]+) MXN al proveedor (\S+) \(([^)]+)\) en (\d+) pago\(s\), pero la suma de facturas del mismo mes es \$([\d,.]+) MXN — desviacion ([\d.]+)%, arriba del 2% permitido/gi,
    "In $1 the company paid \\$$2 MXN to vendor $3 ($4) across $5 payment(s), but same-month invoices sum to \\$$6 MXN — $7% deviation, above the 2% tolerance"],
  [/En (\d{4}-\d{2}) la empresa transfiri[oó] \$([\d,.]+) MXN al proveedor (\S+) \(([^)]+)\) en (\d+) pago\(s\), y no hay ninguna factura de ese proveedor a la empresa en el mismo mes/gi,
    "In $1 the company transferred \\$$2 MXN to vendor $3 ($4) across $5 payment(s), with no invoice from that vendor to the company in the same month"],
  [/Factura de (\S+) a la empresa por \$([\d,.]+) MXN el ([\d-]+)/gi, "Invoice from $1 to the company for \\$$2 MXN on $3"],
  [/Transferencia de la empresa al proveedor por \$([\d,.]+) MXN el ([\d-]+)/gi, "Bank transfer from company to vendor for \\$$1 MXN on $2"],
  [/Registro del proveedor (\S+) \(CLABE (\d+), alta ([\d-]+)\)/gi, "Vendor record $1 (CLABE $2, registered $3)"],
  [/Registro del proveedor (\S+) \(CLABE (\d+)\)/gi, "Vendor record $1 (CLABE $2)"],
  [/PO (\S+) por \$([\d,.]+) MXN el ([\d-]+), aprobada por ([^.]+)/gi, "PO $1 for \\$$2 MXN on $3, approved by $4"],
  [/\brecibio\b/gi, "received"],

  // Individual words (last)
  [/\bfactura\(s\)/gi, "invoice(s)"],
  [/\bfacturas\b/gi, "invoices"],
  [/\bfactura\b/gi, "invoice"],
  [/\btransferencia\(s\)/gi, "transfer(s)"],
  [/\btransferencia\b/gi, "transfer"],
  [/\bpago\(s\)\b/gi, "payment(s)"],
  [/\bpagos\b/gi, "payments"],
  [/\bpago\b/gi, "payment"],
  [/\bproveedor\b/gi, "vendor"],
  [/\bempresa\b/gi, "company"],
  [/\borden de compra\b/gi, "purchase order"],
  [/\bcontrato\b/gi, "contract"],
  [/\brevision manual\b/gi, "manual review"],
  [/\brevisi[oó]n manual\b/gi, "manual review"],
  [/\bpag[oó]\b/gi, "paid"],
  [/\btransfiri[oó]\b/gi, "transferred"],
  [/\baprob[oó]\b/gi, "approved"],
  [/\bemiti[oó]\b/gi, "issued"],
  [/\bpublicado\b/gi, "published"],
  [/\bumbral\b/gi, "threshold"],
  [/\bfraccionar\b/gi, "split"],
];

export function translate(text: string): string {
  let out = text;
  for (const [pattern, replacement] of REPLACEMENTS) {
    if (typeof replacement === "string") {
      out = out.replace(pattern, replacement);
    } else {
      out = out.replace(pattern, replacement);
    }
  }
  return out;
}

// Recursively translate string fields in an object/array. Non-string values pass through.
export function translateDeep<T>(input: T): T {
  if (typeof input === "string") return translate(input) as unknown as T;
  if (Array.isArray(input)) return input.map((v) => translateDeep(v)) as unknown as T;
  if (input && typeof input === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(input as Record<string, unknown>)) {
      out[k] = translateDeep(v);
    }
    return out as unknown as T;
  }
  return input;
}
