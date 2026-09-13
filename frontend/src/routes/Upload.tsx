import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Upload as UploadIcon, FileCheck2, AlertCircle, Loader2, Download, Building2, ShieldCheck, Database as DatabaseIcon, Trash2, Play, ChevronRight, XCircle, CheckCircle2 } from "lucide-react";
import { ESTATE_TABLES, type TableSpec } from "@/lib/estateSchema";
import { parseFile, type ParseResult, type Row } from "@/lib/parseCsv";
import { buildEstate, downloadBytes } from "@/lib/buildEstate";
import { useEstate } from "@/hooks/useEstate";
import { useSubmission } from "@/hooks/useSubmission";
import { fetchHealth, followJob, startInvestigation, type HealthInfo } from "@/lib/apiClient";
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
  const { label: estateLabel, tables: estateTables, totalRows: estateRows, adoptEstate, forgetEstate } = useEstate();
  const [attaching, setAttaching] = useState(false);
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
      // El estate se queda EN LA APP, no solo se descarga: es contra lo que
      // el case file va a verificar cada exhibit. Descargarlo sigue siendo
      // necesario porque el pipeline de Python lo recibe como archivo.
      await adoptEstate(bytes, `estate_${slug}.db`);
      downloadBytes(bytes, `estate_${slug}.db`);
    } catch (err) {
      setBuildError((err as Error).message);
    } finally {
      setBuilding(false);
    }
  }

  // Abrir un .db ya existente — el que descargaste antes, o uno que salio
  // del generador de Python (data/estates/*.db). Sin esto, un auditor que
  // ya tiene su estate no puede verificar nada sin reconstruirlo.
  async function handleAttachDb(file: File | null) {
    if (!file) return;
    setBuildError(null);
    setAttaching(true);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      await adoptEstate(bytes, file.name);
    } catch (err) {
      setBuildError(`No se pudo abrir ${file.name}: ${(err as Error).message}`);
    } finally {
      setAttaching(false);
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

      <section className={cn(
        "rounded-lg border p-5 space-y-3",
        estateLabel ? "border-success/40 bg-surface" : "border-border bg-surface",
      )}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <DatabaseIcon className={cn("h-4 w-4", estateLabel ? "text-success" : "text-muted-foreground")} />
            <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Estate loaded in this browser
            </h2>
          </div>
          {estateLabel && (
            <button
              onClick={() => { void forgetEstate(); }}
              className="mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-destructive flex items-center gap-1 cursor-pointer"
            >
              <Trash2 className="h-3 w-3" /> forget
            </button>
          )}
        </div>

        {estateLabel ? (
          <>
            <p className="mono text-xs text-success">
              {estateLabel} · {estateRows.toLocaleString()} rows
            </p>
            <p className="mono text-[10px] text-muted-foreground/70">
              Every exhibit in the case file now resolves against this estate — the real record, not the model's own note. Peso reconciliation is recomputed here too.
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
              {estateTables.filter((t) => t.present && t.rows > 0).map((t) => (
                <span key={t.name} className="mono text-[10px] text-muted-foreground">
                  {t.name} <span className="text-foreground">{t.rows.toLocaleString()}</span>
                </span>
              ))}
            </div>
          </>
        ) : (
          <p className="mono text-[10px] text-muted-foreground">
            No estate loaded. Findings will still render, but their exhibits cannot be verified against source records. Build one below, or attach an existing .db.
          </p>
        )}

        <label className="block pt-1">
          <input
            type="file"
            accept=".db,.sqlite,.sqlite3"
            className="hidden"
            onChange={(e) => { void handleAttachDb(e.target.files?.[0] ?? null); }}
          />
          <span className="inline-block cursor-pointer border border-dashed border-border hover:border-primary/40 rounded-md px-3 py-2 mono text-[10px] text-muted-foreground hover:text-foreground transition-colors">
            {attaching ? "Opening…" : "Attach an existing estate .db (e.g. data/estates/estate_0001.db)"}
          </span>
        </label>
      </section>

      <InvestigatePanel />

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
        <div className="mono text-[10px] text-muted-foreground/70 mt-3 space-y-1">
          <p>
            The estate stays loaded here for verification. To get findings, the Python side still has to investigate it — that step runs Gemma locally and cannot happen in the browser:
          </p>
          <p className="text-primary">bash scripts/demo_desde_db.sh ~/Downloads/estate_{company.rfc || "COMPANY"}.db</p>
          <p>
            That runs the pipeline, copies <code>submission.json</code> into <code>frontend/public/out/</code>, and prints what changed. Then reload this page — the estate survives the reload.
          </p>
        </div>
      </section>
    </div>
  );
}

/** Correr la investigacion sin salir de la pagina.
 *
 * El servidor local (src/api.py) es opcional a proposito: si no esta
 * corriendo, esto explica como levantarlo y el camino por terminal sigue
 * ahi. Lo que ya no pasa es que el producto te suelte a medio flujo con un
 * archivo descargado y ninguna instruccion visible. */
function InvestigatePanel() {
  const { db, label: estateLabel } = useEstate();
  const { applySubmission } = useSubmission();
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [maxLeads, setMaxLeads] = useState(4);
  const [running, setRunning] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [result, setResult] = useState<{ findings: number; leads: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchHealth(ctrl.signal)
      .then(setHealth)
      .finally(() => setChecking(false));
    return () => ctrl.abort();
  }, []);

  // El log crece hacia abajo: seguir la ultima linea es lo que uno haria
  // mirando la terminal.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);

  async function handleRun() {
    if (!db) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setLines([]);
    try {
      const bytes = db.export();
      const jobId = await startInvestigation(bytes, { maxLeads });
      const final = await followJob(jobId, (nuevas) => {
        setLines((prev) => [...prev, ...nuevas]);
      });
      if (final.status === "error" || !final.submission) {
        setError(final.error ?? "La investigacion fallo sin decir por que.");
      } else {
        applySubmission(final.submission);
        setResult({
          findings: final.submission.findings.length,
          leads: final.submission.leads_not_pursued.length,
        });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  const serverUp = health !== null;
  const modelReady = health?.ollama_reachable === true && health?.model_installed === true;

  return (
    <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
      <div className="flex items-start gap-2">
        <Play className="h-4 w-4 text-primary shrink-0 mt-0.5" />
        <div>
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Investigate</h2>
          <p className="mono text-[10px] text-muted-foreground/70 mt-0.5">
            Runs the full pipeline — detectors, CART, Gemma, validator, challenger — against the loaded estate.
          </p>
        </div>
      </div>

      {checking ? (
        <p className="mono text-[10px] text-muted-foreground">checking for the local server…</p>
      ) : !serverUp ? (
        <div className="rounded-md border border-dashed border-border px-3 py-3 space-y-1">
          <p className="mono text-[10px] text-muted-foreground">
            The local server is not running, so the investigation has to be started from a terminal:
          </p>
          <p className="mono text-[10px] text-primary">python3 -m src.api</p>
          <p className="mono text-[10px] text-muted-foreground/70">
            It needs no extra dependencies. Leave it running and this panel takes over — or keep using{" "}
            <span className="text-primary">bash scripts/demo_desde_db.sh</span> instead.
          </p>
        </div>
      ) : (
        <>
          <div className={cn(
            "rounded-md border px-3 py-2 flex items-start gap-2",
            modelReady ? "border-success/30 bg-success/5" : "border-warning/40 bg-warning/5",
          )}>
            {modelReady
              ? <CheckCircle2 className="h-3.5 w-3.5 text-success shrink-0 mt-0.5" />
              : <AlertCircle className="h-3.5 w-3.5 text-warning shrink-0 mt-0.5" />}
            <div className="mono text-[10px]">
              {modelReady ? (
                <span className="text-success">server up · {health?.model} ready</span>
              ) : !health?.ollama_reachable ? (
                <span className="text-warning">
                  server up, but Ollama is not answering at {health?.base_url} — start it with <span className="text-foreground">ollama serve</span>. You can still run without the model (deterministic stages only, no findings).
                </span>
              ) : (
                <span className="text-warning">
                  server up, but {health?.model} is not installed. Installed: {health?.models_installed.join(", ") || "none"}. Run <span className="text-foreground">bash scripts/setup_llm.sh</span>.
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">Leads to investigate</span>
              <input
                type="number"
                min={1}
                max={100}
                value={maxLeads}
                onChange={(e) => setMaxLeads(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
                className="mono bg-background border border-border rounded-md px-3 py-2 text-sm text-foreground w-28 focus:border-primary focus:outline-none"
              />
            </label>
            <button
              onClick={() => { void handleRun(); }}
              disabled={!db || running}
              className={cn(
                "mono text-[11px] uppercase tracking-wider px-4 py-2 rounded-md flex items-center gap-2 transition-colors",
                db && !running
                  ? "bg-primary text-primary-foreground hover:bg-primary-hover cursor-pointer"
                  : "bg-muted text-muted-foreground cursor-not-allowed",
              )}
            >
              {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {running ? "Investigating…" : "Run investigation"}
            </button>
            {!db && (
              <span className="mono text-[10px] text-muted-foreground">load an estate first</span>
            )}
            {db && estateLabel && !running && (
              <span className="mono text-[10px] text-muted-foreground">on {estateLabel}</span>
            )}
          </div>

          {(running || lines.length > 0) && (
            <div
              ref={logRef}
              className="rounded-md border border-border bg-background p-3 max-h-56 overflow-y-auto"
            >
              {lines.length === 0 ? (
                <p className="mono text-[10px] text-muted-foreground">
                  starting… a 12B model takes 10–40s per turn, so the first line can take a moment
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {lines.map((l, i) => (
                    <li key={i} className="mono text-[10px] text-muted-foreground whitespace-pre-wrap">{l}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {error && (
            <div className="rounded-md border border-destructive/50 bg-destructive/5 px-3 py-2 flex items-start gap-2">
              <XCircle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
              <p className="mono text-[10px] text-destructive break-all">{error}</p>
            </div>
          )}

          {result && (
            <div className="rounded-md border border-success/40 bg-success/5 px-3 py-2 flex items-center justify-between gap-3">
              <p className="mono text-[10px] text-success">
                done · {result.findings} finding{result.findings === 1 ? "" : "s"} · {result.leads} lead{result.leads === 1 ? "" : "s"} not pursued
              </p>
              <Link to={result.findings > 0 ? "/case" : "/leads"} className="mono text-[10px] text-primary hover:underline flex items-center gap-1 shrink-0">
                {result.findings > 0 ? "open case file" : "see why"} <ChevronRight className="h-3 w-3" />
              </Link>
            </div>
          )}
        </>
      )}
    </section>
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
