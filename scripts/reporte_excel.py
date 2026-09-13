#!/usr/bin/env python3
"""
scripts/reporte_excel.py — el expediente en Excel, y la trazabilidad completa
de un caso: de la acusacion hasta el registro crudo en SQLite.

    # todo lo que salio de una corrida
    python3 scripts/reporte_excel.py --submission salida.json \\
        --estate data/estates/estate_0001.db --salida reporte.xlsx

    # un caso concreto, buscado POR NOMBRE de la empresa
    python3 scripts/reporte_excel.py --submission salida.json \\
        --estate data/estates/estate_0001.db --empresa "Servicios Integrales"

    # sin submission previo: corre el pipeline y reporta de una vez
    python3 scripts/reporte_excel.py --estate data/estates/estate_0001.db \\
        --empresa "Servicios Integrales"

`--empresa` acepta el nombre (o un pedazo del nombre, sin importar acentos
ni mayusculas) o directamente el RFC. Si el nombre coincide con varias
empresas, el script las lista y te pide elegir en vez de adivinar.

Si la empresa que buscas NO fue acusada, el reporte lo dice y muestra POR
QUE se descarto —que senal la levanto, que la cerro y con que razon—, que
suele ser mas util que el hallazgo mismo.

HOJAS DEL LIBRO
  Resumen        empresa auditada, totales, metricas y embudo de la corrida
  Hallazgos      una fila por acusacion, con narrativa y monto reclamado
  Trazabilidad   la ruta del dinero paso a paso: de quien a quien, cuanto,
                 que dia, y el registro bancario exacto que lo prueba
  Evidencia      cada exhibit con el CONTENIDO CRUDO de su registro en
                 SQLite, para que un auditor verifique sin abrir la base
  Descartados    los leads que no se acusaron y la razon de cada uno

La cadena completa es: acusacion -> exhibit_id -> tabla y record_id ->
la fila real. Ningun eslabon se escribe a mano: el validador determinista
ya confirmo que cada record_id existe y que los montos reconcilian antes de
que el hallazgo se imprimiera.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PK_POR_TABLA = {
    "ledger": "entry_id", "invoices": "uuid", "bank_txns": "txn_id",
    "vendors": "rfc", "efos_list": "rfc", "purchase_orders": "po_id",
    "contracts": "contract_id", "employees": "emp_id",
}

AZUL = "1F3864"
GRIS = "F2F2F2"


def norm(s) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


# ---------------------------------------------------------------------------
# Resolver "el nombre de una empresa" a un RFC
# ---------------------------------------------------------------------------

def resolver_empresa(con: sqlite3.Connection, texto: str) -> str:
    """Devuelve 'RFC:XXXX'. Acepta el RFC, 'RFC:XXXX', o un pedazo del nombre."""
    limpio = texto.strip()
    candidato = limpio[4:] if limpio.upper().startswith("RFC:") else limpio
    candidato = candidato.upper().replace(" ", "")
    fila = con.execute("SELECT rfc FROM vendors WHERE rfc = ?", (candidato,)).fetchone()
    if fila:
        return f"RFC:{fila[0]}"
    if limpio.upper().startswith("EMP:") or limpio.upper().startswith("EMP-"):
        return limpio.upper().replace("EMP-", "EMP:")

    objetivo = norm(limpio)
    vistos: dict[str, str] = {}
    for tabla, col_id, col_nombre in (("vendors", "rfc", "legal_name"),
                                      ("efos_list", "rfc", "legal_name"),
                                      ("employees", "emp_id", "name")):
        for rid, nombre in con.execute(f"SELECT {col_id}, {col_nombre} FROM {tabla}"):
            if nombre and objetivo in norm(nombre):
                clave = rid if str(rid).startswith("EMP") else f"RFC:{rid}"
                vistos.setdefault(clave, nombre)

    if not vistos:
        raise SystemExit(
            f"\nNingun proveedor, empleado ni RFC del listado 69-B de esta estate "
            f"coincide con '{texto}'.\n"
            f"Los nombres viven en la tabla vendors de la estate. Para ver los que hay:\n"
            f"  python3 scripts/reporte_excel.py --estate <estate.db> --listar-empresas")
    if len(vistos) > 1:
        print(f"\n'{texto}' coincide con {len(vistos)} entidades. Se mas especifico "
              f"o pasa el RFC directo:\n")
        for clave, nombre in sorted(vistos.items(), key=lambda kv: kv[1]):
            print(f"  {clave:22s} {nombre}")
        raise SystemExit(1)
    return next(iter(vistos))


def listar_empresas(con: sqlite3.Connection) -> None:
    filas = con.execute(
        "SELECT rfc, legal_name, category FROM vendors ORDER BY legal_name").fetchall()
    print(f"\n{len(filas)} proveedores en esta estate:\n")
    for rfc, nombre, cat in filas:
        print(f"  RFC:{rfc:16s} {(nombre or '(sin razon social)'):48s} {cat or ''}")


# ---------------------------------------------------------------------------

def registro_crudo(con: sqlite3.Connection, tabla: str, record_id: str) -> dict:
    """La fila real de SQLite detras de un exhibit. Es el ultimo eslabon de la
    trazabilidad: lo que un auditor abriria para no creernos nada."""
    pk = PK_POR_TABLA.get(tabla)
    if not pk:
        return {}
    con.row_factory = sqlite3.Row
    fila = con.execute(f"SELECT * FROM {tabla} WHERE {pk} = ?", (record_id,)).fetchone()
    return dict(fila) if fila else {}


def nombre_de(con: sqlite3.Connection, entidad: str) -> str:
    if entidad.startswith("EMP:"):
        f = con.execute("SELECT name, role FROM employees WHERE emp_id = ?",
                        (entidad,)).fetchone()
        return f"{f[0]} ({f[1]})" if f else ""
    rfc = entidad.replace("RFC:", "")
    f = con.execute("SELECT legal_name FROM vendors WHERE rfc = ?", (rfc,)).fetchone()
    if f and f[0]:
        return f[0]
    f = con.execute("SELECT legal_name FROM efos_list WHERE rfc = ?", (rfc,)).fetchone()
    return (f[0] if f else "") or ""


def resumen_crudo(registro: dict) -> str:
    """El registro crudo en una celda legible: campo=valor, sin los vacios."""
    return " | ".join(f"{k}={v}" for k, v in registro.items() if v not in (None, ""))


# ---------------------------------------------------------------------------
# Construccion del libro
# ---------------------------------------------------------------------------

def construir_libro(sub: dict, con: sqlite3.Connection, entidad: str | None,
                    salida: Path, estate_path: Path) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise SystemExit("Hace falta openpyxl:  pip install openpyxl\n"
                         "(o usa --formato csv)")

    findings = sub.get("findings", [])
    descartados = sub.get("leads_not_pursued", [])
    if entidad:
        findings = [f for f in findings if entidad in f.get("entities", [])]
        descartados = [d for d in descartados if d.get("entity") == entidad]

    wb = Workbook()
    encabezado = Font(bold=True, color="FFFFFF")
    relleno = PatternFill("solid", fgColor=AZUL)

    def hoja(titulo, columnas, filas, anchos=None, wrap=()):
        ws = wb.create_sheet(titulo)
        ws.append(columnas)
        for c in range(1, len(columnas) + 1):
            celda = ws.cell(1, c)
            celda.font, celda.fill = encabezado, relleno
            celda.alignment = Alignment(vertical="center")
        for fila in filas:
            ws.append(fila)
        for i, ancho in enumerate(anchos or [18] * len(columnas), 1):
            ws.column_dimensions[get_column_letter(i)].width = ancho
        for col in wrap:
            for fila in range(2, ws.max_row + 1):
                ws.cell(fila, col).alignment = Alignment(wrap_text=True, vertical="top")
        for fila in range(2, ws.max_row + 1):
            for c in range(1, len(columnas) + 1):
                if isinstance(ws.cell(fila, c).value, float):
                    ws.cell(fila, c).number_format = '#,##0.00'
        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
        return ws

    wb.remove(wb.active)

    # ---- Resumen ----------------------------------------------------------
    md = sub.get("run_metadata", {})
    embudo = md.get("embudo", {})
    emp = con.execute("SELECT receiver_rfc, COUNT(*) n FROM invoices "
                      "GROUP BY receiver_rfc ORDER BY n DESC LIMIT 1").fetchone()
    fechas = con.execute("SELECT MIN(issue_date), MAX(issue_date) FROM invoices").fetchone()
    total_reclamado = round(sum(float(f.get("peso_amount") or 0) for f in findings), 2)

    filas_resumen = [
        ("Estate", str(estate_path)),
        ("Empresa auditada", f"RFC:{emp[0]}" if emp else "(no inferida)"),
        ("Periodo de las facturas", f"{fechas[0]} a {fechas[1]}" if fechas else ""),
        ("Caso filtrado", f"{entidad} — {nombre_de(con, entidad)}" if entidad else "(todos)"),
        ("", ""),
        ("Hallazgos", len(findings)),
        ("Monto total reclamado (MXN)", total_reclamado),
        ("Hallazgos 'proven'", sum(1 for f in findings if f.get("confidence") == "proven")),
        ("Hallazgos 'probable'", sum(1 for f in findings if f.get("confidence") == "probable")),
        ("Leads descartados", len(descartados)),
        ("", ""),
        ("Llamadas al modelo", md.get("llm_calls", 0)),
        ("Costo imputado (MXN)", md.get("mxn_cost", 0.0)),
        ("Segundos de corrida", md.get("wall_clock_seconds", 0.0)),
    ]
    for k, v in embudo.items():
        filas_resumen.append((f"Embudo: {k.replace('_', ' ')}", v))
    ws = hoja("Resumen", ["Concepto", "Valor"], filas_resumen, [34, 62])
    ws.auto_filter.ref = None

    # ---- Hallazgos --------------------------------------------------------
    filas = []
    for i, f in enumerate(findings, 1):
        ents = f.get("entities", [])
        filas.append([
            f"H{i:02d}",
            ", ".join(ents),
            " / ".join(filter(None, (nombre_de(con, e) for e in ents))),
            f.get("scheme_type", ""),
            f.get("confidence", ""),
            float(f.get("peso_amount") or 0),
            f.get("rule_broken", ""),
            f.get("narrative", ""),
            len(f.get("exhibits", [])),
            len(f.get("money_trail", [])),
        ])
    hoja("Hallazgos",
         ["#", "Entidades", "Nombre", "Tipo de esquema", "Confianza",
          "Monto reclamado (MXN)", "Regla violada", "Narrativa",
          "Exhibits", "Pasos de la ruta"],
         filas, [6, 24, 34, 20, 12, 20, 40, 80, 10, 16], wrap=(7, 8))

    # ---- Trazabilidad (la ruta del dinero) --------------------------------
    filas = []
    for i, f in enumerate(findings, 1):
        por_id = {e["exhibit_id"]: e for e in f.get("exhibits", [])}
        pasos = f.get("money_trail", [])
        if not pasos:
            filas.append([f"H{i:02d}", "", "(sin movimiento bancario)", "", None, "",
                          "", "La acusacion es documental: facturas y listado 69-B, "
                          "sin transferencia que seguir.", ""])
            continue
        for n, paso in enumerate(pasos, 1):
            ex = por_id.get(paso.get("exhibit_id"), {})
            crudo = registro_crudo(con, ex.get("source_table", ""),
                                   ex.get("record_id", "")) if ex else {}
            filas.append([
                f"H{i:02d}", n, paso.get("from", ""), paso.get("to", ""),
                float(paso.get("amount") or 0), paso.get("date", ""),
                paso.get("exhibit_id", ""),
                f"{ex.get('source_table', '')}/{ex.get('record_id', '')}",
                resumen_crudo(crudo),
            ])
    hoja("Trazabilidad",
         ["Hallazgo", "Paso", "De", "A", "Monto (MXN)", "Fecha", "Exhibit",
          "Registro citado", "Contenido real del registro"],
         filas, [10, 6, 28, 28, 16, 12, 10, 34, 90], wrap=(9,))

    # ---- Evidencia --------------------------------------------------------
    filas = []
    for i, f in enumerate(findings, 1):
        for ex in f.get("exhibits", []):
            tabla, rid = ex.get("source_table", ""), ex.get("record_id", "")
            crudo = registro_crudo(con, tabla, rid)
            filas.append([f"H{i:02d}", ex.get("exhibit_id", ""), tabla, rid,
                          ex.get("note", ""),
                          "si" if crudo else "NO EXISTE",
                          resumen_crudo(crudo)])
    hoja("Evidencia",
         ["Hallazgo", "Exhibit", "Tabla", "record_id", "Que prueba",
          "Existe en SQLite", "Contenido real del registro"],
         filas, [10, 10, 18, 40, 56, 16, 90], wrap=(5, 7))

    # ---- Descartados ------------------------------------------------------
    filas = [[d.get("entity", ""), nombre_de(con, d.get("entity", "")),
              d.get("signal", ""), d.get("closed_by", ""), d.get("reason", ""),
              ", ".join(d.get("tool_calls_made", []) or [])]
             for d in descartados]
    hoja("Descartados",
         ["Entidad", "Nombre", "Senal que la levanto", "Cerrado por",
          "Razon", "Herramientas usadas"],
         filas, [24, 34, 28, 14, 80, 40], wrap=(5,))

    salida.parent.mkdir(parents=True, exist_ok=True)
    wb.save(salida)


# ---------------------------------------------------------------------------

def imprimir_trazabilidad(findings: list[dict], con: sqlite3.Connection) -> None:
    """La cadena completa en la terminal, para no abrir el Excel solo por verla:
    narrativa -> cada salto del dinero -> el registro que lo prueba."""
    for i, f in enumerate(findings, 1):
        print(f"\n{'=' * 72}\n  TRAZABILIDAD H{i:02d} — {f.get('scheme_type')} "
              f"({f.get('confidence')})\n{'=' * 72}")
        print(f"  Regla: {f.get('rule_broken', '')}")
        print(f"\n  {f.get('narrative', '')}\n")

        por_id = {e["exhibit_id"]: e for e in f.get("exhibits", [])}
        pasos = f.get("money_trail", [])
        if pasos:
            print("  RUTA DEL DINERO")
            for n, p in enumerate(pasos, 1):
                ex = por_id.get(p.get("exhibit_id"), {})
                print(f"    {n}. {p.get('from')}")
                print(f"       └─ ${float(p.get('amount') or 0):,.2f}  {p.get('date')}"
                      f"   [{p.get('exhibit_id')}: "
                      f"{ex.get('source_table')}/{ex.get('record_id')}]")
                print(f"    → {p.get('to')}")
        else:
            print("  RUTA DEL DINERO: ninguna. La acusacion es documental "
                  "(facturas y listado 69-B), no hay transferencia que seguir.")

        print("\n  EVIDENCIA (cada una verificada contra SQLite por el validador)")
        for ex in f.get("exhibits", []):
            crudo = registro_crudo(con, ex.get("source_table", ""), ex.get("record_id", ""))
            marca = "ok " if crudo else "NO "
            print(f"    [{marca}] {ex.get('exhibit_id')}  "
                  f"{ex.get('source_table')}/{ex.get('record_id')}")
            print(f"           {ex.get('note', '')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estate", type=Path, required=True)
    ap.add_argument("--submission", type=Path,
                    help="salida.json de una corrida; si falta, se corre el pipeline")
    ap.add_argument("--empresa", help="nombre (o pedazo) o RFC de la entidad a reportar")
    ap.add_argument("--salida", type=Path, help="ruta del .xlsx (por defecto reporte_<caso>.xlsx)")
    ap.add_argument("--listar-empresas", action="store_true",
                    help="imprime los proveedores de la estate y termina")
    ap.add_argument("--sin-modelo", action="store_true",
                    help="si hay que correr el pipeline, hacerlo sin LLM")
    ap.add_argument("--max-leads", type=int, default=12)
    args = ap.parse_args()

    if not args.estate.exists():
        raise SystemExit(f"No existe la estate: {args.estate}")
    con = sqlite3.connect(f"file:{args.estate}?mode=ro", uri=True)

    if args.listar_empresas:
        listar_empresas(con)
        return 0

    entidad = resolver_empresa(con, args.empresa) if args.empresa else None

    if args.submission:
        sub = json.loads(args.submission.read_text(encoding="utf-8"))
        origen = str(args.submission)
    else:
        from src.forensic.client import LLMClient
        from src.pipeline import ejecutar
        from src.tools import EstateDB
        print("Sin --submission: corriendo el pipeline"
              + (" (sin modelo)" if args.sin_modelo else " con el modelo local") + "...")
        cliente = None if args.sin_modelo else LLMClient()
        with EstateDB(args.estate) as estate:
            sub = ejecutar(estate, cliente, max_leads=args.max_leads)
        origen = "corrida de este momento"

    salida = args.salida or REPO / (
        f"reporte_{entidad.replace(':', '_')}.xlsx" if entidad else "reporte.xlsx")
    construir_libro(sub, con, entidad, salida, args.estate)

    findings = [f for f in sub.get("findings", [])
                if not entidad or entidad in f.get("entities", [])]
    descartados = [d for d in sub.get("leads_not_pursued", [])
                   if not entidad or d.get("entity") == entidad]

    print(f"\nFuente: {origen}")
    if entidad:
        print(f"Caso  : {entidad} — {nombre_de(con, entidad) or '(sin razon social)'}")
    print(f"Excel : {salida}")

    if findings:
        print(f"\n{len(findings)} hallazgo(s):")
        for f in findings:
            pasos = len(f.get("money_trail", []))
            print(f"  {f.get('scheme_type')}  ${float(f.get('peso_amount') or 0):,.2f}  "
                  f"({f.get('confidence')}, {len(f.get('exhibits', []))} exhibits, "
                  f"{pasos} paso(s) de ruta del dinero)")
        if entidad:
            imprimir_trazabilidad(findings, con)
    elif entidad:
        print("\nNo se acuso a esta entidad.")
        for d in descartados:
            print(f"  senal: {d.get('signal')}\n  cerrado por: {d.get('closed_by')}"
                  f"\n  razon: {d.get('reason')}")
        if not descartados:
            print("  Tampoco aparecio como lead: ninguna regla determinista disparo "
                  "sobre ella.\n  Para ver sus features y por que ninguna regla la "
                  f"levanto:\n    python3 scripts/explicar.py --estate {args.estate} "
                  f"--entidad {entidad}")

    print(f"\nLa misma trazabilidad, en expediente narrado (markdown + HTML con "
          f"diagrama):\n  python3 -m src.casefile --submission "
          f"{args.submission or 'salida.json'} --estate {args.estate} --out-dir expediente/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
