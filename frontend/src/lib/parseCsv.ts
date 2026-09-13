import Papa from "papaparse";
import * as XLSX from "xlsx";
import type { ColumnSpec, TableSpec } from "./estateSchema";

export type Row = Record<string, string | number | null>;

export interface ParseResult {
  table: string;
  rows: Row[];
  warnings: string[];
  errors: string[];
}

// Parse a File (CSV or XLSX) into `Row[]` and validate against a `TableSpec`.
// Coerces numeric columns; empty strings become `null` for nullable columns.
export async function parseFile(file: File, spec: TableSpec): Promise<ParseResult> {
  const name = file.name.toLowerCase();
  const isXlsx = name.endsWith(".xlsx") || name.endsWith(".xls");
  const raw: Row[] = isXlsx ? await parseXlsx(file) : await parseCsv(file);
  return validate(raw, spec);
}

async function parseCsv(file: File): Promise<Row[]> {
  const text = await file.text();
  return new Promise((resolve, reject) => {
    Papa.parse<Row>(text, {
      header: true,
      skipEmptyLines: true,
      complete: (res) => resolve(res.data as Row[]),
      error: reject,
    });
  });
}

async function parseXlsx(file: File): Promise<Row[]> {
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const first = wb.SheetNames[0];
  const sheet = wb.Sheets[first];
  return XLSX.utils.sheet_to_json<Row>(sheet, { defval: "" });
}

function validate(rows: Row[], spec: TableSpec): ParseResult {
  const warnings: string[] = [];
  const errors: string[] = [];
  const known = new Set(spec.columns.map((c) => c.name));
  const headers = rows.length > 0 ? Object.keys(rows[0]) : [];

  const missing = spec.columns.filter((c) => c.required && !headers.includes(c.name));
  if (missing.length > 0) {
    errors.push(`Missing required columns: ${missing.map((c) => c.name).join(", ")}`);
  }

  const extra = headers.filter((h) => !known.has(h));
  if (extra.length > 0) {
    warnings.push(`Ignoring unknown columns: ${extra.join(", ")}`);
  }

  const cleaned: Row[] = rows.map((row, i) => {
    const out: Row = {};
    for (const col of spec.columns) {
      const rawVal = row[col.name];
      out[col.name] = coerce(rawVal, col, i, errors);
    }
    return out;
  });

  return { table: spec.name, rows: cleaned, warnings, errors };
}

function coerce(v: unknown, col: ColumnSpec, rowIdx: number, errors: string[]): string | number | null {
  if (v === undefined || v === null || v === "") {
    if (col.required) errors.push(`Row ${rowIdx + 1}: missing required '${col.name}'`);
    return null;
  }
  if (col.type === "INTEGER") {
    const n = Number(v);
    if (!Number.isFinite(n)) {
      errors.push(`Row ${rowIdx + 1}: '${col.name}' expected INTEGER, got '${v}'`);
      return null;
    }
    return Math.trunc(n);
  }
  if (col.type === "REAL") {
    const n = Number(v);
    if (!Number.isFinite(n)) {
      errors.push(`Row ${rowIdx + 1}: '${col.name}' expected REAL, got '${v}'`);
      return null;
    }
    return n;
  }
  return String(v);
}
