// Estate schema mirrors docs/spec/estate_schema.sql. Every table maps to one
// CSV/XLSX file the auditor uploads. Column names must stay in sync with the
// Python side — src/tools/estate_access.py reads these exact names via SQLite.

export interface TableSpec {
  name: string;
  label: string;
  description: string;
  primaryKey: string;
  columns: ColumnSpec[];
  minRows?: number;
}

export interface ColumnSpec {
  name: string;
  type: "TEXT" | "INTEGER" | "REAL";
  required: boolean;
  hint?: string;
}

export const ESTATE_TABLES: TableSpec[] = [
  {
    name: "vendors",
    label: "Vendors",
    description: "Registered suppliers (RFC, legal name, CLABE, category).",
    primaryKey: "rfc",
    columns: [
      { name: "rfc", type: "TEXT", required: true, hint: "12–13 char Mexican tax id" },
      { name: "legal_name", type: "TEXT", required: true },
      { name: "registered_date", type: "TEXT", required: false, hint: "ISO 8601" },
      { name: "address", type: "TEXT", required: false },
      { name: "bank_clabe", type: "TEXT", required: false, hint: "18-digit CLABE" },
      { name: "category", type: "TEXT", required: false },
      { name: "contact_email", type: "TEXT", required: false },
    ],
  },
  {
    name: "invoices",
    label: "Invoices (CFDI)",
    description: "Issued and received CFDIs. Amount lives in `total`.",
    primaryKey: "uuid",
    columns: [
      { name: "uuid", type: "TEXT", required: true, hint: "CFDI UUID" },
      { name: "issuer_rfc", type: "TEXT", required: true },
      { name: "receiver_rfc", type: "TEXT", required: true },
      { name: "issue_date", type: "TEXT", required: true },
      { name: "subtotal", type: "REAL", required: false },
      { name: "iva", type: "REAL", required: false, hint: "16% VAT" },
      { name: "total", type: "REAL", required: true, hint: "cited for peso reconciliation" },
      { name: "concepto_text", type: "TEXT", required: false, hint: "free-text description" },
      { name: "uso_cfdi", type: "TEXT", required: false, hint: "SAT catalog code, e.g. G03" },
      { name: "forma_pago", type: "TEXT", required: false },
      { name: "metodo_pago", type: "TEXT", required: false, hint: "PUE | PPD" },
      { name: "status", type: "TEXT", required: false, hint: "vigente | cancelado" },
    ],
  },
  {
    name: "ledger",
    label: "Ledger (GL)",
    description: "General ledger entries. Nullable invoice_uuid links entry to invoice.",
    primaryKey: "entry_id",
    columns: [
      { name: "entry_id", type: "INTEGER", required: true },
      { name: "date", type: "TEXT", required: true },
      { name: "account_code", type: "TEXT", required: true },
      { name: "account_name", type: "TEXT", required: false },
      { name: "debit", type: "REAL", required: false },
      { name: "credit", type: "REAL", required: false },
      { name: "description", type: "TEXT", required: false },
      { name: "invoice_uuid", type: "TEXT", required: false, hint: "nullable" },
      { name: "cost_center", type: "TEXT", required: false },
      { name: "approver", type: "TEXT", required: false, hint: "who signed off" },
    ],
  },
  {
    name: "bank_txns",
    label: "Bank transactions",
    description: "SPEI / cheque / cash movements. Amount cited for reconciliation.",
    primaryKey: "txn_id",
    columns: [
      { name: "txn_id", type: "TEXT", required: true },
      { name: "date", type: "TEXT", required: true },
      { name: "from_clabe", type: "TEXT", required: true },
      { name: "to_clabe", type: "TEXT", required: true },
      { name: "amount", type: "REAL", required: true },
      { name: "reference", type: "TEXT", required: false },
      { name: "channel", type: "TEXT", required: false, hint: "SPEI | cheque | efectivo" },
    ],
  },
  {
    name: "purchase_orders",
    label: "Purchase orders",
    description: "POs with approver — the approval-limit trail lives here.",
    primaryKey: "po_id",
    columns: [
      { name: "po_id", type: "TEXT", required: true },
      { name: "vendor_rfc", type: "TEXT", required: true },
      { name: "date", type: "TEXT", required: true },
      { name: "amount", type: "REAL", required: true },
      { name: "requester", type: "TEXT", required: false },
      { name: "approver", type: "TEXT", required: false },
      { name: "description", type: "TEXT", required: false },
    ],
  },
  {
    name: "contracts",
    label: "Contracts",
    description: "Master service agreements tying a vendor to a scope.",
    primaryKey: "contract_id",
    columns: [
      { name: "contract_id", type: "TEXT", required: true },
      { name: "vendor_rfc", type: "TEXT", required: true },
      { name: "start_date", type: "TEXT", required: true },
      { name: "value", type: "REAL", required: false },
      { name: "scope_text", type: "TEXT", required: false },
    ],
  },
  {
    name: "employees",
    label: "Employees",
    description: "Employee registry — required for kickback detection.",
    primaryKey: "emp_id",
    columns: [
      { name: "emp_id", type: "TEXT", required: true, hint: 'e.g. "EMP:0001"' },
      { name: "name", type: "TEXT", required: true },
      { name: "role", type: "TEXT", required: false },
      { name: "bank_clabe", type: "TEXT", required: false, hint: "required for employee linkage" },
      { name: "hire_date", type: "TEXT", required: false },
    ],
  },
  {
    name: "efos_list",
    label: "SAT 69-B list (EFOS)",
    description: "Mexican tax authority list of shell taxpayers.",
    primaryKey: "rfc",
    columns: [
      { name: "rfc", type: "TEXT", required: true },
      { name: "legal_name", type: "TEXT", required: false },
      { name: "status", type: "TEXT", required: true, hint: "definitivo | presunto | desvirtuado | favorable" },
      { name: "publication_date", type: "TEXT", required: false },
    ],
  },
];

export function getTable(name: string): TableSpec | undefined {
  return ESTATE_TABLES.find((t) => t.name === name);
}
