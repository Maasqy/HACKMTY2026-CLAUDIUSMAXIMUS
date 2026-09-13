// El estate que el auditor carga, conservado y consultable desde la UI.
//
// POR QUE EXISTE. buildEstate.ts construia el .db, lo descargaba y lo
// tiraba. El dashboard solo leia submission.json — las CONCLUSIONES — sin
// acceso a la EVIDENCIA que citan, asi que un exhibit solo podia mostrar la
// nota que el propio modelo escribio sobre el. El modelo citandose a si
// mismo no es verificacion: es una afirmacion de verificabilidad.
//
// Con el estate vivo aqui, cada exhibit se resuelve contra el registro real
// (SELECT * FROM bank_txns WHERE txn_id = ...), la reconciliacion de pesos
// se recalcula en el navegador, y un record_id inventado se ve como lo que
// es — un hueco, en rojo, en vez de pasar desapercibido.
//
// Se persiste en IndexedDB porque el flujo EXIGE un reload: construyes el
// estate, corres el pipeline de Python en la terminal, copias
// submission.json a frontend/public/out/ y recargas. Un estate solo en
// memoria se perderia justo cuando llegan los hallazgos que tiene que
// verificar.

import initSqlJs, { type Database, type SqlJsStatic, type Statement } from "sql.js";
import sqlWasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { ESTATE_TABLES } from "./estateSchema";

const IDB_NAME = "fraud-forensics";
const IDB_STORE = "estate";
const IDB_KEY = "current";
const IDB_VERSION = 1;

export interface StoredEstate {
  bytes: Uint8Array;
  label: string;
  savedAt: string;
}

export type EstateRecord = Record<string, string | number | Uint8Array | null>;

// --- sql.js ---------------------------------------------------------------

let sqlJsPromise: Promise<SqlJsStatic> | null = null;

function getSqlJs(): Promise<SqlJsStatic> {
  // El wasm se sirve local (ver buildEstate.ts): nada de CDN en tiempo de
  // corrida, para que esto funcione igual sin internet.
  if (!sqlJsPromise) sqlJsPromise = initSqlJs({ locateFile: () => sqlWasmUrl });
  return sqlJsPromise;
}

export async function openEstate(bytes: Uint8Array): Promise<Database> {
  const SQL = await getSqlJs();
  return new SQL.Database(bytes);
}

// --- IndexedDB ------------------------------------------------------------

function openIdb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, IDB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("no se pudo abrir IndexedDB"));
  });
}

export async function saveEstateBytes(bytes: Uint8Array, label: string): Promise<void> {
  const idb = await openIdb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = idb.transaction(IDB_STORE, "readwrite");
      const value: StoredEstate = { bytes, label, savedAt: new Date().toISOString() };
      tx.objectStore(IDB_STORE).put(value, IDB_KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("no se pudo guardar el estate"));
      tx.onabort = () => reject(tx.error ?? new Error("se aborto el guardado del estate"));
    });
  } finally {
    idb.close();
  }
}

export async function loadEstateBytes(): Promise<StoredEstate | null> {
  const idb = await openIdb();
  try {
    return await new Promise<StoredEstate | null>((resolve, reject) => {
      const tx = idb.transaction(IDB_STORE, "readonly");
      const req = tx.objectStore(IDB_STORE).get(IDB_KEY);
      req.onsuccess = () => resolve((req.result as StoredEstate | undefined) ?? null);
      req.onerror = () => reject(req.error ?? new Error("no se pudo leer el estate"));
    });
  } finally {
    idb.close();
  }
}

export async function clearEstateBytes(): Promise<void> {
  const idb = await openIdb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = idb.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).delete(IDB_KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("no se pudo borrar el estate"));
    });
  } finally {
    idb.close();
  }
}

// --- consultas ------------------------------------------------------------

export interface TableSummary {
  name: string;
  label: string;
  rows: number;
  present: boolean;
}

export function summarizeEstate(db: Database): TableSummary[] {
  return ESTATE_TABLES.map((spec) => {
    try {
      const res = db.exec(`SELECT COUNT(*) FROM "${spec.name}"`);
      const raw = res[0]?.values?.[0]?.[0];
      return { name: spec.name, label: spec.label, rows: Number(raw ?? 0), present: true };
    } catch {
      // La tabla no existe en este .db — legitimo: el importador permite
      // saltarse tablas opcionales.
      return { name: spec.name, label: spec.label, rows: 0, present: false };
    }
  });
}

/** El registro real que respalda un exhibit, o null si no existe.
 *
 * `null` NO es un detalle tecnico: significa que la acusacion cita un
 * record_id que no esta en la base. Es exactamente la alucinacion que el
 * validador deterministico de Python frena, y la UI tiene que mostrarla
 * como el hueco que es. */
export function lookupRecord(db: Database, table: string, recordId: string): EstateRecord | null {
  const spec = ESTATE_TABLES.find((t) => t.name === table);
  if (!spec) return null;
  let stmt: Statement;
  try {
    stmt = db.prepare(`SELECT * FROM "${spec.name}" WHERE "${spec.primaryKey}" = :id LIMIT 1`);
  } catch {
    return null; // la tabla no existe en este estate
  }
  try {
    stmt.bind({ ":id": recordId });
    if (!stmt.step()) return null;
    return stmt.getAsObject() as EstateRecord;
  } catch {
    return null;
  } finally {
    stmt.free();
  }
}

// --- reconciliacion de pesos ---------------------------------------------

// ESPEJO de src/config.py. Tiene que mantenerse en sync: el validador de
// Python reconcilia contra estas mismas columnas y esta misma tolerancia.
// Si divergen, la UI pintaria una palomita verde sobre algo que el backend
// (y el validador oficial de los jueces) rechaza — el peor error posible
// aqui, porque es mentir con confianza.
export const AMOUNT_COLUMNS: Record<string, string> = {
  invoices: "total",
  bank_txns: "amount",
  purchase_orders: "amount",
  contracts: "value",
};
export const PESO_TOLERANCE = 0.02;

export interface ExhibitRef {
  source_table: string;
  record_id: string;
}

export interface TableSum {
  table: string;
  sum: number;
  count: number;
}

export interface Reconciliation {
  declared: number;
  verified: number;
  missing: string[];
  byTable: TableSum[];
  bestTable: string | null;
  bestSum: number;
  deviationPct: number;
  reconciles: boolean;
  ok: boolean;
}

/** Rehace, en el navegador, la misma verificacion que corrio el validador
 * de Python — para que el auditor la VEA en vez de tener que creerla.
 *
 * Los montos se suman POR TABLA y se comparan contra la tabla mas cercana,
 * nunca sumados entre tablas: una factura y la transferencia que la pago
 * son el mismo dinero visto dos veces, y sumarlas duplicaria el monto
 * aparente. Es la regla que documenta docs/spec/submission_schema.json
 * (_peso_reconciliation_rule) y la que aplica validate_format.py. */
export function reconcile(
  db: Database,
  peso_amount: number,
  exhibits: ExhibitRef[],
): Reconciliation {
  const sums = new Map<string, TableSum>();
  const missing: string[] = [];
  let verified = 0;

  for (const ex of exhibits) {
    const record = lookupRecord(db, ex.source_table, ex.record_id);
    if (!record) {
      missing.push(`${ex.source_table}/${ex.record_id}`);
      continue;
    }
    verified += 1;

    const col = AMOUNT_COLUMNS[ex.source_table];
    if (!col) continue; // vendors / efos_list / ledger no llevan monto propio
    const raw = record[col];
    const amount = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(amount)) continue;

    const entry = sums.get(ex.source_table);
    if (entry) {
      entry.sum += amount;
      entry.count += 1;
    } else {
      sums.set(ex.source_table, { table: ex.source_table, sum: amount, count: 1 });
    }
  }

  const byTable = [...sums.values()].sort((a, b) => a.table.localeCompare(b.table));
  const declared = Number(peso_amount) || 0;

  let bestTable: string | null = null;
  let bestSum = 0;
  for (const t of byTable) {
    if (bestTable === null || Math.abs(declared - t.sum) < Math.abs(declared - bestSum)) {
      bestTable = t.table;
      bestSum = t.sum;
    }
  }

  const deviation = byTable.length === 0
    ? 1
    : Math.abs(bestSum - declared) / Math.max(declared, 1);
  const reconciles = byTable.length > 0 && deviation <= PESO_TOLERANCE;

  return {
    declared,
    verified,
    missing,
    byTable,
    bestTable,
    bestSum,
    deviationPct: deviation * 100,
    reconciles,
    ok: missing.length === 0 && reconciles,
  };
}
