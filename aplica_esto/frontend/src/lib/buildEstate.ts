import initSqlJs, { type Database } from "sql.js";
// Bundled locally (Vite's `?url` import) instead of fetched from
// sql.js.org at runtime. The CDN fetch is a single point of failure — any
// network hiccup, ad blocker, or offline demo throws "both async and sync
// fetching of the wasm failed" right here, even though the exact same
// wasm file already ships inside node_modules/sql.js/dist/. This also
// matches the rest of the project: the whole pipeline is designed to run
// without network access, so the estate-builder shouldn't be the one part
// that needs it.
import sqlWasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { ESTATE_TABLES, type TableSpec } from "./estateSchema";
import type { Row } from "./parseCsv";

// Build a SQLite database in-browser from parsed CSV/XLSX rows.
// Returns the raw .db bytes ready for download or Python ingestion.
export async function buildEstate(parsed: Record<string, Row[]>): Promise<Uint8Array> {
  const SQL = await initSqlJs({
    locateFile: () => sqlWasmUrl,
  });
  const db: Database = new SQL.Database();

  for (const spec of ESTATE_TABLES) {
    db.run(createTableSql(spec));
    const rows = parsed[spec.name] ?? [];
    if (rows.length === 0) continue;
    insertRows(db, spec, rows);
  }

  const bytes = db.export();
  db.close();
  return bytes;
}

function createTableSql(spec: TableSpec): string {
  const cols = spec.columns.map((c) => {
    const notNull = c.required ? " NOT NULL" : "";
    const pk = c.name === spec.primaryKey ? " PRIMARY KEY" : "";
    return `"${c.name}" ${c.type}${notNull}${pk}`;
  });
  return `CREATE TABLE IF NOT EXISTS "${spec.name}" (\n  ${cols.join(",\n  ")}\n);`;
}

function insertRows(db: Database, spec: TableSpec, rows: Row[]): void {
  const colNames = spec.columns.map((c) => c.name);
  const placeholders = colNames.map(() => "?").join(", ");
  const sql = `INSERT OR REPLACE INTO "${spec.name}" (${colNames.map((c) => `"${c}"`).join(", ")}) VALUES (${placeholders});`;
  const stmt = db.prepare(sql);
  try {
    for (const row of rows) {
      const bindValues = colNames.map((name) => {
        const v = row[name];
        if (v === null || v === undefined) return null;
        return v as string | number;
      });
      stmt.run(bindValues);
    }
  } finally {
    stmt.free();
  }
}

// Trigger a browser download of the built .db.
export function downloadBytes(bytes: Uint8Array, filename: string): void {
  const blob = new Blob([bytes as BlobPart], { type: "application/vnd.sqlite3" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
