import { useMemo, useState } from "react";
import { Upload as UploadIcon, FileCheck2, AlertCircle, Loader2, Download, Building2, ShieldCheck } from "lucide-react";
import { ESTATE_TABLES, type TableSpec } from "@/lib/estateSchema";
import { parseFile, type ParseResult, type Row } from "@/lib/parseCsv";
import { buildEstate, downloadBytes } from "@/lib/buildEstate";
import { cn } from "@/lib/utils";

interface FileState {
  file: File | null;
  result: ParseResult | null;
  parsing: boolean;
}

interface CompanyInfo {
  legal_name: string;
  rfc: string;
  fiscal_year: string;
  industry: string;
  contact_email: string;
}

const EMPTY_COMPANY: CompanyInfo = {
  legal_name: "",
  rfc: "",
  fiscal_year: "2026",
  industry: "",
  contact_email: "",
};

export default function Upload() {
  const [company, setCompany] = useState<CompanyInfo>(EMPTY_COMPANY);
  const [files, setFiles] = useState<Record<string, FileState>>(() => {
    const init: Record<string, FileState> = {};
    ESTATE_TABLES.forEach((t) => { init[t.name] = { file: null, result: null, parsing: false }; });
    return init;
  });
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  const totalRows = useMemo(
    () => Object.values(files).reduce((s, f) => s + (f.result?.rows.length ?? 0), 0),
    [files],
  );
  const totalErrors = useMemo(
    () => Object.values(files).reduce((s, f) => s + (f.result?.errors.length ?? 0), 0),
    [files],
  );
  const missingOptional = useMemo(
    () => ESTATE_TABLES.filter((t) => !files[t.name].file).map((t) => t.label),
    [files],
  );

  async function handleFile(spec: TableSpec, file: File | null) {
    if (!file) {
      setFiles((prev) => ({ ...prev, [spec.name]: { file: null, result: null, parsing: false } }));
      return;
    }
    setFiles((prev) => ({ ...prev, [spec.name]: { file, result: null, parsing: true } }));
    try {
      const result = await parseFile(file, spec);
      setFiles((prev) => ({ ...prev, [spec.name]: { file, result, parsing: false } }));
    } catch (err) {
      setFiles((prev) => ({
        ...prev,
        [spec.name]: {
          file,
          result: { table: spec.name, rows: [], warnings: [], errors: [(err as Error).message] },
          parsing: false,
        },
      }));
    }
  }

  async function handleBuild() {
    setBuildError(null);
    setBuilding(true);
    try {
      const parsed: Record<string, Row[]> = {};
      Object.entries(files).forEach(([name, state]) => {
        if (state.result) parsed[name] = state.result.rows;
      });
      const bytes = await buildEstate(parsed);
      const slug = company.rfc || "company";
      downloadBytes(bytes, `estate_${slug}.db`);
    } catch (err) {
      setBuildError((err as Error).message);
    } finally {
      setBuilding(false);
    }
  }

  const canBuild = totalRows > 0 && totalErrors === 0 && company.legal_name.trim() !== "" && company.rfc.trim() !== "";

  return (
    <div className="p-8 space-y-6 animate-fade-in max-w-5xl">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold text-foreground">Load company data</h1>
        <p className="text-sm text-muted-foreground">
          Upload the eight ledgers as CSV or XLSX. Fraud Forensics packages them into a deterministic SQLite estate that the Python pipeline can audit — everything happens in your browser, nothing is uploaded.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-surface p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-primary" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Company under audit</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Legal name" value={company.legal_name} onChange={(v) => setCompany({ ...company, legal_name: v })} placeholder="e.g. Servicios Corporativos Alfa S.A. de C.V." required />
          <Field label="RFC" value={company.rfc} onChange={(v) => setCompany({ ...company, rfc: v.toUpperCase() })} placeholder="e.g. UDA230508OIG" required mono />
          <Field label="Fiscal year" value={company.fiscal_year} onChange={(v) => setCompany({ ...company, fiscal_year: v })} placeholder="2026" mono />
          <Field label="Industry" value={company.industry} onChange={(v) => setCompany({ ...company, industry: v })} placeholder="e.g. Manufacturing" />
          <Field label="Contact email" value={company.contact_email} onChange={(v) => setCompany({ ...company, contact_email: v })} placeholder="cfo@company.mx" />
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <UploadIcon className="h-4 w-4 text-primary" />
            <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Financial ledgers · 8 files</h2>
          </div>
          <span className="mono text-[10px] text-muted-foreground">CSV or XLSX · headers must match column names</span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {ESTATE_TABLES.map((spec) => (
            <FileDropzone
              key={spec.name}
              spec={spec}
              state={files[spec.name]}
              onFile={(f) => handleFile(spec, f)}
            />
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-primary/30 bg-surface p-5 shadow-glow">
        <div className="flex items-start gap-2 mb-3">
          <ShieldCheck className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <div>
            <h2 className="mono text-[10px] uppercase tracking-widest text-primary">Build estate</h2>
            <p className="mono text-[10px] text-muted-foreground/70 mt-0.5">
              Produces a deterministic SQLite .db — same input, same file byte-for-byte.
            </p>
          </div>
        </div>
        <dl className="grid grid-cols-3 gap-3 mb-4">
          <SummaryStat label="Total rows" value={totalRows.toLocaleString()} />
          <SummaryStat label="Parse errors" value={String(totalErrors)} tone={totalErrors === 0 ? "good" : "bad"} />
          <SummaryStat label="Files missing" value={String(missingOptional.length)} tone={missingOptional.length === 0 ? "good" : "warn"} />
        </dl>
        {missingOptional.length > 0 && (
          <p className="mono text-[10px] text-muted-foreground mb-3">
            Optional to skip: {missingOptional.join(", ")}. The pipeline runs with whatever is provided but recall drops on missing ledgers.
          </p>
        )}
        {buildError && (
          <p className="mono text-[11px] text-destructive mb-3">Build failed: {buildError}</p>
        )}
        <button
          onClick={handleBuild}
          disabled={!canBuild || building}
          className={cn(
            "mono text-[11px] uppercase tracking-wider px-4 py-2 rounded-md flex items-center gap-2 transition-colors",
            canBuild && !building
              ? "bg-primary text-primary-foreground hover:bg-primary-hover cursor-pointer"
              : "bg-muted text-muted-foreground cursor-not-allowed",
          )}
        >
          {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          {building ? "Building SQLite…" : "Build & download estate.db"}
        </button>
        <p className="mono text-[10px] text-muted-foreground/70 mt-3">
          Next: hand the downloaded <code className="text-primary">estate_{company.rfc || "COMPANY"}.db</code> to <code className="text-primary">python -m src.run --estate &lt;path&gt; --out submission.json</code>, then copy the output to <code className="text-primary">frontend/public/out/</code> and reload this page.
        </p>
      </section>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, required, mono }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; required?: boolean; mono?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}{required && <span className="text-primary ml-1">*</span>}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          "bg-background border border-border rounded-md px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none",
          mono && "mono",
        )}
      />
    </label>
  );
}

function SummaryStat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "warn" }) {
  const color = tone === "good" ? "text-success" : tone === "bad" ? "text-destructive" : tone === "warn" ? "text-warning" : "text-foreground";
  return (
    <div>
      <div className="mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn("mono text-2xl font-semibold mt-0.5", color)}>{value}</div>
    </div>
  );
}

function FileDropzone({ spec, state, onFile }: { spec: TableSpec; state: FileState; onFile: (f: File | null) => void }) {
  const ok = state.result && state.result.errors.length === 0 && state.result.rows.length > 0;
  const bad = state.result && state.result.errors.length > 0;
  return (
    <div className={cn(
      "rounded-lg border bg-surface p-4 transition-colors",
      ok ? "border-success/40" : bad ? "border-destructive/40" : "border-border",
    )}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="text-sm font-semibold text-foreground flex items-center gap-2">
            {spec.label}
            {ok && <FileCheck2 className="h-3.5 w-3.5 text-success" />}
            {bad && <AlertCircle className="h-3.5 w-3.5 text-destructive" />}
          </div>
          <p className="mono text-[10px] text-muted-foreground mt-0.5">{spec.description}</p>
        </div>
        <span className="mono text-[9px] uppercase tracking-wider text-muted-foreground shrink-0">{spec.name}</span>
      </div>
      <label className="block">
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          className="hidden"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
        <span className={cn(
          "block text-center cursor-pointer border border-dashed rounded-md px-3 py-3 mono text-[11px] transition-colors",
          state.file ? "border-primary/40 text-primary hover:bg-primary/5" : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
        )}>
          {state.parsing ? "Parsing…" : state.file ? `${state.file.name} · ${(state.result?.rows.length ?? 0).toLocaleString()} rows` : "Click to select CSV or XLSX"}
        </span>
      </label>
      {state.result && state.result.errors.length > 0 && (
        <ul className="mt-2 space-y-0.5 max-h-24 overflow-y-auto">
          {state.result.errors.slice(0, 5).map((e, i) => (
            <li key={i} className="mono text-[10px] text-destructive">• {e}</li>
          ))}
          {state.result.errors.length > 5 && (
            <li className="mono text-[10px] text-destructive/70">+ {state.result.errors.length - 5} more</li>
          )}
        </ul>
      )}
      {state.result && state.result.warnings.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {state.result.warnings.slice(0, 2).map((w, i) => (
            <li key={i} className="mono text-[10px] text-warning">! {w}</li>
          ))}
        </ul>
      )}
      <details className="mt-2 group">
        <summary className="mono text-[10px] text-muted-foreground cursor-pointer hover:text-foreground">expected columns ({spec.columns.length})</summary>
        <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5">
          {spec.columns.map((c) => (
            <div key={c.name} className="mono text-[10px]">
              <span className={c.required ? "text-primary" : "text-muted-foreground"}>{c.name}</span>
              <span className="text-muted-foreground/50 ml-1">{c.type.toLowerCase()}</span>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
