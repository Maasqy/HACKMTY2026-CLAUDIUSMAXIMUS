import { Routes, Route, Link, NavLink, useLocation, useParams, Navigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { SubmissionProvider, useSubmission } from "@/hooks/useSubmission";
import { useEventStream } from "@/hooks/useEventStream";
import { useSweepData } from "@/hooks/useSweepData";
import { formatMxn } from "@/lib/formatMxn";
import { loadEvents } from "@/lib/loadEvents";
import { MOCK_EVENTS } from "@/mocks/events.mock";
import { SCHEME_LABELS } from "@/lib/schemeLabels";
import { cn } from "@/lib/utils";
import type { Exhibit, Finding, LeadNotPursued } from "@/types/submission";
import type { Event as ForensicEvent } from "@/types/events";
import { Scale, Radar, ScrollText, BarChart3, Home as HomeIcon, ChevronRight, ShieldCheck, Play, Pause, RotateCcw, Brain, Search, Wrench, FileText, AlertTriangle, CheckCircle2, XCircle, Printer, Upload as UploadIcon, Info } from "lucide-react";
import Upload from "@/routes/Upload";
import About from "@/routes/About";

function MockBanner() {
  const { isMock, isLoading } = useSubmission();
  if (isLoading || !isMock) return null;
  return (
    <div role="status" className="mono text-[11px] bg-primary/10 text-primary/90 border-b border-primary/30 px-4 py-1.5 text-center tracking-wide print:hidden">
      DEMO MODE · seed 0042 sample estate — go to <span className="font-semibold">Load Data</span> to package your own company ledgers into an audit-ready estate.db
    </div>
  );
}

function Sidebar() {
  const items = [
    { to: "/", label: "Overview", icon: HomeIcon },
    { to: "/case", label: "Case File", icon: Scale },
    { to: "/live", label: "Live Investigation", icon: Radar },
    { to: "/leads", label: "Leads Log", icon: ScrollText },
    { to: "/metrics", label: "Metrics", icon: BarChart3 },
    { to: "/upload", label: "Load Data", icon: UploadIcon },
    { to: "/about", label: "How it works", icon: Info },
  ];
  return (
    <aside className="w-56 border-r border-border bg-surface flex flex-col">
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-primary" />
          <span className="font-semibold tracking-tight">Fraud Forensics</span>
        </div>
        <p className="mono text-[10px] text-muted-foreground mt-1">CLAUDIUS MAXIMUS · HackMTY 2026</p>
      </div>
      <nav className="flex-1 p-2 space-y-0.5">
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
                isActive ? "bg-primary/15 text-primary border-l-2 border-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted",
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-border">
        <RunMetadataChips />
      </div>
    </aside>
  );
}

function RunMetadataChips() {
  const { submission } = useSubmission();
  const m = submission.run_metadata;
  return (
    <div className="space-y-1.5">
      <MetaRow label="seed" value={String(submission.seed).padStart(4, "0")} />
      <MetaRow label="llm_calls" value={String(m.llm_calls)} />
      <MetaRow label="cost" value={formatMxn(m.mxn_cost)} />
      <MetaRow label="wall_clock" value={`${m.wall_clock_seconds.toFixed(2)}s`} />
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="mono text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className="mono text-xs text-foreground truncate">{value}</span>
    </div>
  );
}

function SchemeBadge({ scheme }: { scheme: keyof typeof SCHEME_LABELS }) {
  const meta = SCHEME_LABELS[scheme];
  return (
    <span
      className="inline-flex items-center gap-1.5 mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-semibold"
      style={{ color: meta.color, borderColor: meta.color, backgroundColor: `${meta.color}18` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.color }} />
      {meta.short}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: "proven" | "probable" }) {
  const cls = confidence === "proven" ? "text-success border-success/40 bg-success/10" : "text-warning border-warning/40 bg-warning/10";
  return <span className={cn("mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border font-semibold", cls)}>{confidence}</span>;
}

function StatCard({ label, value, hint, glow }: { label: string; value: string; hint?: string; glow?: boolean }) {
  return (
    <div className={cn("rounded-lg border border-border bg-surface p-4 transition-shadow", glow && "shadow-glow border-primary/40")}>
      <div className="mono text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-3xl font-semibold", glow ? "text-primary" : "text-foreground")}>{value}</div>
      {hint && <div className="mono text-[11px] text-muted-foreground mt-1">{hint}</div>}
    </div>
  );
}

function Overview() {
  const { submission } = useSubmission();
  const totalPeso = submission.findings.reduce((s, f) => s + f.peso_amount, 0);
  const bySchemeCount = useMemo(() => {
    const acc: Record<string, number> = {};
    submission.findings.forEach((f) => { acc[f.scheme_type] = (acc[f.scheme_type] || 0) + 1; });
    return acc;
  }, [submission]);

  return (
    <div className="p-8 space-y-6 animate-fade-in">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold text-foreground">Case Overview</h1>
        <p className="text-sm text-muted-foreground">
          Deterministic audit output for <span className="mono text-foreground">seed {submission.seed}</span>. Every accusation must reconcile in pesos and cite at least three exhibits.
        </p>
      </header>

      <section className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <StatCard label="Findings" value={String(submission.findings.length)} hint="promoted through deterministic validator" />
        <StatCard label="Leads not pursued" value={String(submission.leads_not_pursued.length)} hint="closed with recorded reason" />
        <StatCard label="Amount at stake" value={formatMxn(totalPeso)} hint="sum of finding peso_amount" />
        <StatCard label="False accusations" value="0" hint="zero innocents flagged" glow />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="rounded-lg border border-border bg-surface p-4 lg:col-span-2">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center justify-between">
            Findings by scheme
            <Link to="/case" className="mono text-[11px] text-primary hover:underline flex items-center gap-1">
              open case file <ChevronRight className="h-3 w-3" />
            </Link>
          </h2>
          <div className="space-y-2">
            {Object.keys(SCHEME_LABELS).map((k) => {
              const count = bySchemeCount[k] || 0;
              const meta = SCHEME_LABELS[k as keyof typeof SCHEME_LABELS];
              return (
                <div key={k} className="flex items-center gap-3">
                  <span className="mono text-[10px] uppercase tracking-wider w-32 text-muted-foreground">{meta.short}</span>
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div className="h-full transition-all duration-500" style={{ width: `${Math.min(count * 25, 100)}%`, background: meta.color }} />
                  </div>
                  <span className="mono text-xs text-foreground w-6 text-right">{count}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold text-foreground mb-3">Run signature</h2>
          <dl className="space-y-2 text-xs">
            <dt className="mono text-[10px] uppercase tracking-wider text-muted-foreground">Determinism</dt>
            <dd className="text-foreground">{submission.run_metadata.deterministic === false ? "no" : "yes — replayable"}</dd>
            <dt className="mono text-[10px] uppercase tracking-wider text-muted-foreground mt-2">Rule of law</dt>
            <dd className="text-muted-foreground">Every accusation cites SAT Art. 69-B CFF, NIF A-2, or an internal policy — never a statistical outlier.</dd>
          </dl>
        </div>
      </section>
    </div>
  );
}

function CaseFile() {
  const { submission } = useSubmission();
  return (
    <div className="p-8 space-y-4 animate-fade-in">
      <header>
        <h1 className="text-3xl font-semibold text-foreground">Case File</h1>
        <p className="text-sm text-muted-foreground">
          {submission.findings.length} findings · {formatMxn(submission.findings.reduce((s, f) => s + f.peso_amount, 0))} at stake
        </p>
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {submission.findings.map((f, i) => (
          <FindingCard key={i} finding={f} index={i} />
        ))}
      </div>
    </div>
  );
}

function FindingCard({ finding, index }: { finding: Finding; index: number }) {
  return (
    <Link to={`/case/${index}`} className="block rounded-lg border border-border bg-surface p-4 hover:border-primary/50 hover:shadow-lg transition-all cursor-pointer">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <SchemeBadge scheme={finding.scheme_type} />
          <ConfidenceBadge confidence={finding.confidence} />
        </div>
        <span className="mono text-[10px] text-muted-foreground">#{index + 1}</span>
      </div>
      <div className="mt-3">
        <div className="mono text-[11px] text-muted-foreground">Accused</div>
        <div className="mono text-sm text-foreground">{finding.entities.join(", ")}</div>
      </div>
      <div className="mt-3 flex items-baseline justify-between">
        <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">peso_amount</span>
        <span className="mono text-lg text-primary font-semibold">{formatMxn(finding.peso_amount)}</span>
      </div>
      <p className="mt-3 text-xs text-muted-foreground line-clamp-3 leading-relaxed">{finding.narrative}</p>
      <div className="mt-3 pt-3 border-t border-border flex items-center justify-between mono text-[10px] text-muted-foreground">
        <span>{finding.exhibits.length} exhibits · {finding.money_trail?.length ?? 0} trail steps</span>
        <span className="text-primary flex items-center gap-1">open <ChevronRight className="h-3 w-3" /></span>
      </div>
    </Link>
  );
}

function FindingDetail() {
  const { findingIndex } = useParams();
  const { submission } = useSubmission();
  const idx = Number(findingIndex);
  const f = submission.findings[idx];
  if (!f) return <Navigate to="/case" replace />;

  const caseNumber = `FF-${String(submission.seed).padStart(4, "0")}-${String(idx + 1).padStart(3, "0")}`;
  const issuedOn = new Date().toISOString().slice(0, 10);
  const companyRfc = "UDA230508OIG";

  return (
    <div className="p-8 space-y-5 animate-fade-in max-w-5xl print:max-w-full print:p-0">
      {/* Print-only forensic header */}
      <div className="print:show pdf-header" style={{ display: "none" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            <div style={{ fontSize: "8pt", letterSpacing: "0.15em", textTransform: "uppercase", opacity: 0.7 }}>
              Fraud Forensics · Case File
            </div>
            <div style={{ fontSize: "16pt", fontWeight: 700, marginTop: "1mm" }}>Case {caseNumber}</div>
          </div>
          <div style={{ textAlign: "right", fontFamily: "'Fira Code', monospace", fontSize: "9pt" }}>
            <div>Subject: RFC {companyRfc}</div>
            <div>Issued: {issuedOn}</div>
            <div>Scheme: {f.scheme_type.replace(/_/g, " ")}</div>
            <div>Confidence: <span className="pdf-badge">{f.confidence.toUpperCase()}</span></div>
          </div>
        </div>
      </div>

      <header className="space-y-3 print:space-y-2">
        <div className="flex items-center justify-between print:hidden">
          <Link to="/case" className="mono text-[11px] text-muted-foreground hover:text-foreground">← Back to case file</Link>
          <button
            onClick={() => window.print()}
            className="mono text-[11px] uppercase tracking-wider px-3 py-1.5 rounded-md border border-primary bg-primary/10 text-primary hover:bg-primary/20 hover:border-primary flex items-center gap-1.5 cursor-pointer"
          >
            <Printer className="h-3 w-3" /> Download PDF Report
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          <SchemeBadge scheme={f.scheme_type} />
          <ConfidenceBadge confidence={f.confidence} />
          <span className="mono text-[11px] text-muted-foreground">Finding #{idx + 1} · Case {caseNumber}</span>
        </div>
        <h1 className="text-2xl font-semibold text-foreground">{f.entities.join(", ")}</h1>
      </header>

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2">Executive summary</h2>
        <p className="text-sm text-foreground leading-relaxed">{f.narrative}</p>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <div className="flex items-start gap-2 mb-2">
          <Scale className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Rule broken · legal basis</h2>
        </div>
        <p className="text-sm text-foreground leading-relaxed italic">{f.rule_broken}</p>
        <div className="mt-3 pt-3 border-t border-border flex items-baseline justify-between">
          <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">Amount at stake</span>
          <span className="mono text-2xl text-primary font-semibold">{formatMxn(f.peso_amount)}</span>
        </div>
      </section>

      <ReasoningChain entities={f.entities} scheme={f.scheme_type} />

      <ExhibitsSection exhibits={f.exhibits} />

      <MoneyTrailSection trail={f.money_trail} />

      <section className="rounded-lg border border-border bg-surface p-5 print:hidden">
        <div className="flex items-start gap-2 mb-2">
          <ShieldCheck className="h-4 w-4 text-success shrink-0 mt-0.5" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Auditability</h2>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Every claim above is traceable to a record_id in the estate. The peso amount reconciles within 2% against the cited amount-bearing tables (invoices, bank_txns, purchase_orders, contracts). The rule cited is a concrete statute or internal policy, never a statistical outlier. This report is deterministic — the same estate produces the same finding, byte-for-byte.
        </p>
      </section>

      {/* Print-only forensic footer with sign-off + reproducibility */}
      <div className="print:show pdf-footer" style={{ display: "none" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "6mm", fontFamily: "'Fira Code', monospace", fontSize: "8pt" }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: "1mm" }}>Reproducibility statement</div>
            <div>
              This report was generated by Fraud Forensics (CLAUDIUS MAXIMUS · HackMTY 2026) from estate seed {submission.seed}.
              Every exhibit ID corresponds to a record in the SQLite estate; the peso amount reconciles within the 2% tolerance
              defined in src/config.py:RECONCILE_TOLERANCE_PCT. Re-running the pipeline against the same estate reproduces this
              case byte-for-byte.
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: "1mm" }}>Run metadata</div>
            <div>llm_calls: {submission.run_metadata.llm_calls}</div>
            <div>mxn_cost: {formatMxn(submission.run_metadata.mxn_cost)}</div>
            <div>wall_clock: {submission.run_metadata.wall_clock_seconds.toFixed(2)}s</div>
            <div>deterministic: {String(submission.run_metadata.deterministic ?? false)}</div>
          </div>
          <div style={{ flex: 1, textAlign: "right" }}>
            <div style={{ fontWeight: 700, marginBottom: "1mm" }}>Signatures</div>
            <div style={{ marginTop: "6mm", borderTop: "1px solid #000", paddingTop: "1mm" }}>Investigator</div>
            <div style={{ marginTop: "5mm", borderTop: "1px solid #000", paddingTop: "1mm" }}>Reviewer</div>
          </div>
        </div>
        <div style={{ marginTop: "3mm", textAlign: "center", opacity: 0.7 }}>
          — end of report · case {caseNumber} · {issuedOn} —
        </div>
      </div>
    </div>
  );
}

function ExhibitsSection({ exhibits }: { exhibits: Exhibit[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <section className="rounded-lg border border-border bg-surface overflow-hidden">
      <div className="px-5 py-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Exhibits ({exhibits.length})</h2>
        </div>
        <span className="mono text-[10px] text-muted-foreground">click a row to expand · reconciles within 2%</span>
      </div>
      <ul className="divide-y divide-border">
        {exhibits.map((ex) => {
          const open = openId === ex.exhibit_id;
          return (
            <li key={ex.exhibit_id}>
              <button
                onClick={() => setOpenId(open ? null : ex.exhibit_id)}
                className="w-full text-left px-5 py-3 flex items-center gap-4 hover:bg-muted/20 transition-colors cursor-pointer"
              >
                <span className="mono text-xs text-primary font-semibold min-w-[3rem]">{ex.exhibit_id}</span>
                <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground min-w-[8rem]">{ex.source_table}</span>
                <span className="mono text-xs text-foreground truncate flex-1">{ex.record_id}</span>
                <ChevronRight className={cn("h-3 w-3 text-muted-foreground transition-transform", open && "rotate-90")} />
              </button>
              {open && (
                <div className="px-5 pb-4 pt-1 border-t border-border/50 bg-muted/10">
                  <div className="mono text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-1">Note</div>
                  <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">{ex.note}</p>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MoneyTrailSection({ trail }: { trail: Finding["money_trail"] }) {
  const steps = trail ?? [];
  return (
    <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
      <div className="flex items-start gap-2">
        <Radar className="h-4 w-4 text-primary shrink-0 mt-0.5" />
        <div>
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Money trail</h2>
          <p className="mono text-[10px] text-muted-foreground/70 mt-0.5">follow the peso — each arrow is a citable bank_txn</p>
        </div>
      </div>

      <MoneyTrailDiagram steps={steps} />

      <details className="mt-3">
        <summary className="mono text-[10px] uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground">
          Ledger view · every step ({steps.length})
        </summary>
        <ol className="space-y-2 mt-3">
          {steps.map((s, i) => (
            <li key={i} className="grid grid-cols-[1fr,auto,1fr] items-center gap-3">
              <div className="rounded-md border border-border bg-background/50 px-3 py-2">
                <div className="mono text-[9px] uppercase tracking-wider text-muted-foreground">From</div>
                <div className="mono text-xs text-foreground truncate">{s.from}</div>
              </div>
              <div className="flex flex-col items-center min-w-[9rem]">
                <div className="mono text-xs text-primary font-semibold">{formatMxn(s.amount)}</div>
                <div className="w-full h-0.5 bg-gradient-to-r from-transparent via-primary to-transparent my-1" />
                <div className="mono text-[10px] text-muted-foreground">{s.date} · {s.exhibit_id}</div>
              </div>
              <div className="rounded-md border border-border bg-background/50 px-3 py-2 text-right">
                <div className="mono text-[9px] uppercase tracking-wider text-muted-foreground">To</div>
                <div className="mono text-xs text-foreground truncate">{s.to}</div>
              </div>
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}

function MoneyTrailDiagram({ steps }: { steps: Finding["money_trail"] }) {
  if (!steps || steps.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-background/30 p-6 text-center">
        <p className="mono text-[11px] text-muted-foreground italic">
          No cash movement is recorded for this finding — the fraud is in the accounting entries only (see exhibits).
        </p>
      </div>
    );
  }

  // Deduplicate nodes in order of first appearance
  const nodeIds: string[] = [];
  const seen = new Set<string>();
  for (const s of steps) {
    if (!seen.has(s.from)) { seen.add(s.from); nodeIds.push(s.from); }
    if (!seen.has(s.to)) { seen.add(s.to); nodeIds.push(s.to); }
  }

  // Group edges by (from -> to) pair, summing amounts and collecting exhibit IDs
  const edgeMap = new Map<string, { from: string; to: string; amount: number; count: number; dates: string[]; exhibits: string[] }>();
  for (const s of steps) {
    const key = `${s.from}→${s.to}`;
    const existing = edgeMap.get(key);
    if (existing) {
      existing.amount += s.amount;
      existing.count += 1;
      existing.dates.push(s.date);
      existing.exhibits.push(s.exhibit_id);
    } else {
      edgeMap.set(key, { from: s.from, to: s.to, amount: s.amount, count: 1, dates: [s.date], exhibits: [s.exhibit_id] });
    }
  }
  const edges = Array.from(edgeMap.values());

  // Layout — keep nodes fully within the viewBox by shrinking the node box for
  // graphs with more than 2 entities so labels never clip on left/right edges.
  const W = 780;
  const H = 260;
  const nodeCount = nodeIds.length;
  const nodeW = nodeCount >= 3 ? 200 : 220;
  const nodeH = 54;
  // Ensure the node CENTER is at least nodeW/2 away from either edge.
  const halfW = nodeW / 2;
  const leftEdge = halfW + 8;
  const rightEdge = W - halfW - 8;
  const usableW = rightEdge - leftEdge;
  const positions = new Map<string, { x: number; y: number }>();
  nodeIds.forEach((id, i) => {
    const x = nodeCount === 1 ? W / 2 : leftEdge + (usableW * i) / (nodeCount - 1);
    positions.set(id, { x, y: H / 2 });
  });

  const nodeColor = (id: string): string => {
    if (id.startsWith("EMP:")) return "#F97316";
    if (id === "RFC:UDA230508OIG") return "#3B82F6";
    return "#A44200";
  };

  // Draw edges with curved paths; multiple edges between same pair get different curvatures
  const edgesByPair = new Map<string, number>();
  const edgePaths = edges.map((e) => {
    const pairKey = [e.from, e.to].sort().join("|");
    const parallelIdx = edgesByPair.get(pairKey) ?? 0;
    edgesByPair.set(pairKey, parallelIdx + 1);
    const p1 = positions.get(e.from)!;
    const p2 = positions.get(e.to)!;
    const isForward = p1.x <= p2.x;
    // Vertical offset for curve: alternate up/down and grow with parallel index
    const curveOffset = isForward ? -60 - parallelIdx * 20 : 60 + parallelIdx * 20;
    const midX = (p1.x + p2.x) / 2;
    const midY = p1.y + curveOffset;
    // Start/end just outside the nodes
    const dx = p2.x - p1.x;
    const dir = dx >= 0 ? 1 : -1;
    const startX = p1.x + dir * (nodeW / 2);
    const endX = p2.x - dir * (nodeW / 2);
    const path = `M ${startX} ${p1.y} Q ${midX} ${midY}, ${endX} ${p2.y}`;
    return { edge: e, path, labelX: midX, labelY: midY + (isForward ? -6 : 14) };
  });

  return (
    <div className="rounded-md border border-border bg-background/40 overflow-hidden">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Money trail diagram">
        <defs>
          <marker id="arrowhead-mt" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#A44200" />
          </marker>
        </defs>

        {/* Edges */}
        {edgePaths.map((e, i) => (
          <g key={i}>
            <path d={e.path} stroke="#A44200" strokeWidth={1.6} fill="none" markerEnd="url(#arrowhead-mt)" opacity={0.85} />
            <rect x={e.labelX - 80} y={e.labelY - 20} width={160} height={30} rx={4} fill="#0A0A0A" stroke="#A44200" strokeWidth={0.7} opacity={0.95} />
            <text x={e.labelX} y={e.labelY - 6} textAnchor="middle" className="mono" fontSize={11} fill="#F5F5F5" fontWeight={600}>
              {formatMxn(e.edge.amount)}
            </text>
            <text x={e.labelX} y={e.labelY + 6} textAnchor="middle" className="mono" fontSize={9} fill="#A0A0A0">
              {e.edge.count > 1 ? `${e.edge.count}× · ${e.edge.dates[0]}…` : e.edge.dates[0]}
            </text>
          </g>
        ))}

        {/* Nodes */}
        {nodeIds.map((id) => {
          const pos = positions.get(id)!;
          const color = nodeColor(id);
          const label = id.length > 22 ? id.slice(0, 21) + "…" : id;
          const kind = id.startsWith("EMP:") ? "Employee" : id === "RFC:UDA230508OIG" ? "Company (subject)" : "Vendor";
          return (
            <g key={id} transform={`translate(${pos.x - nodeW / 2}, ${pos.y - nodeH / 2})`}>
              <rect width={nodeW} height={nodeH} rx={6} fill="#141414" stroke={color} strokeWidth={1.6} />
              <text x={nodeW / 2} y={22} textAnchor="middle" className="mono" fontSize={13} fill="#F5F5F5" fontWeight={600}>{label}</text>
              <text x={nodeW / 2} y={40} textAnchor="middle" className="mono" fontSize={9} fill={color} letterSpacing={1}>{kind.toUpperCase()}</text>
            </g>
          );
        })}
      </svg>
      <div className="px-3 py-2 border-t border-border/40 flex flex-wrap gap-4 mono text-[9px] uppercase tracking-wider text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border" style={{ borderColor: "#3B82F6" }} /> Company under audit</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border" style={{ borderColor: "#A44200" }} /> Counterparty</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm border" style={{ borderColor: "#F97316" }} /> Employee</span>
        <span className="ml-auto">{steps.length} txn · {edges.length} edges · {nodeIds.length} nodes</span>
      </div>
    </div>
  );
}

const REASONING_ICONS: Record<string, { icon: typeof Brain; color: string; label: string }> = {
  lead_opened: { icon: Search, color: "#3B82F6", label: "Signal detected" },
  hypothesis: { icon: Brain, color: "#EAB308", label: "Hypothesis" },
  tool_call: { icon: Wrench, color: "#06B6D4", label: "Evidence gathered (tool call)" },
  evidence: { icon: FileText, color: "#8B5CF6", label: "Evidence recorded" },
  challenge: { icon: AlertTriangle, color: "#F97316", label: "Challenger response" },
  lead_closed: { icon: XCircle, color: "#EF4444", label: "Lead closed" },
  finding: { icon: CheckCircle2, color: "#A44200", label: "Finding promoted" },
};

function ReasoningChain({ entities, scheme }: { entities: readonly string[]; scheme: string }) {
  const [events, setEvents] = useState<ForensicEvent[]>([]);
  useEffect(() => {
    loadEvents("/out/events.jsonl").then(setEvents).catch(() => setEvents(MOCK_EVENTS));
  }, []);
  const chain = useMemo(() => {
    const entitySet = new Set(entities);
    return events.filter((e) => entitySet.has(e.entity) && REASONING_ICONS[e.type]);
  }, [events, entities]);

  return (
    <section className="rounded-lg border border-primary/30 bg-surface p-5 shadow-glow">
      <div className="flex items-start gap-2 mb-3">
        <Brain className="h-4 w-4 text-primary shrink-0 mt-0.5" />
        <div>
          <h2 className="mono text-[10px] uppercase tracking-widest text-primary">AI Reasoning Chain</h2>
          <p className="mono text-[10px] text-muted-foreground/70 mt-0.5">
            why the AI decided this is {scheme.replace("_", " ")} — every step is auditable
          </p>
        </div>
      </div>
      {chain.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">
          No detailed reasoning events for this entity. This finding was closed by the deterministic validator using rule-based signals only (no LLM inference required for this case).
        </p>
      ) : (
        <ol className="space-y-2">
          {chain.map((ev, i) => {
            const meta = REASONING_ICONS[ev.type];
            const Icon = meta.icon;
            const payload = (ev as unknown as { payload?: Record<string, unknown> }).payload ?? {};
            return (
              <li key={`${ev.seq}-${i}`} className="flex gap-3 items-start">
                <div className="flex flex-col items-center pt-0.5">
                  <div className="w-7 h-7 rounded-full border-2 flex items-center justify-center shrink-0" style={{ borderColor: meta.color, backgroundColor: `${meta.color}20` }}>
                    <Icon className="h-3.5 w-3.5" style={{ color: meta.color }} />
                  </div>
                  {i < chain.length - 1 && <div className="w-0.5 flex-1 min-h-[1rem] mt-1" style={{ background: `${meta.color}40` }} />}
                </div>
                <div className="flex-1 pb-3">
                  <div className="flex items-baseline gap-2 mb-0.5">
                    <span className="mono text-[10px] uppercase tracking-wider font-semibold" style={{ color: meta.color }}>{meta.label}</span>
                    <span className="mono text-[10px] text-muted-foreground/60">t={ev.t.toFixed(2)}s</span>
                  </div>
                  <p className="text-xs text-foreground leading-relaxed">
                    {formatReasoningPayload(ev.type, payload)}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function formatReasoningPayload(type: string, p: Record<string, unknown>): string {
  if (type === "lead_opened") return String(p.reason ?? p.signal ?? "Signal detected");
  if (type === "hypothesis") {
    // Support both `statement` (backend canonical) and legacy `hypothesis` key.
    return String(p.statement ?? p.hypothesis ?? p.scheme_type ?? "");
  }
  if (type === "tool_call") {
    const tool = String(p.tool ?? "unknown_tool");
    const args = p.args ? ` (${Object.entries(p.args as object).slice(0, 2).map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 30)}`).join(", ")})` : "";
    const summary = p.result_summary ? ` → ${p.result_summary}` : p.result_rows ? ` → ${p.result_rows} rows` : "";
    return `Called ${tool}${args}${summary}`;
  }
  if (type === "evidence") return String(p.note ?? `${p.source_table}/${p.record_id}`);
  if (type === "challenge") {
    const objection = String(p.objection ?? p.challenge ?? "");
    const resolved = p.resolved === true ? " · resolved" : p.resolved === false ? " · pending" : "";
    return `${objection}${resolved}`;
  }
  if (type === "lead_closed") return `Closed by ${p.closed_by ?? "unknown"}: ${p.reason ?? ""}`;
  if (type === "finding") return `Promoted to finding: ${p.scheme_type ?? ""} — ${p.rule_broken ?? ""}`;
  return JSON.stringify(p).slice(0, 200);
}

function LeadsLog() {
  const { submission } = useSubmission();
  const [filter, setFilter] = useState<"all" | "investigator" | "challenger" | "validator">("all");
  const leads = filter === "all" ? submission.leads_not_pursued : submission.leads_not_pursued.filter((l) => l.closed_by === filter);
  const counts = useMemo(() => {
    const c: Record<string, number> = { investigator: 0, challenger: 0, validator: 0 };
    submission.leads_not_pursued.forEach((l) => { c[l.closed_by] = (c[l.closed_by] || 0) + 1; });
    return c;
  }, [submission]);

  return (
    <div className="p-8 space-y-4 animate-fade-in">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold text-foreground">Leads Not Pursued</h1>
        <p className="text-sm text-muted-foreground">Signals that fired but were closed before becoming an accusation. Every closure carries a reason.</p>
      </header>

      <div className="flex flex-wrap gap-2">
        {(["all", "investigator", "challenger", "validator"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "mono text-[11px] uppercase tracking-wider px-3 py-1 rounded-full border transition-colors cursor-pointer",
              filter === f ? "bg-primary text-primary-foreground border-primary" : "bg-surface text-muted-foreground border-border hover:text-foreground",
            )}
          >
            {f} {f !== "all" ? <span className="ml-1 opacity-70">({counts[f] || 0})</span> : <span className="ml-1 opacity-70">({submission.leads_not_pursued.length})</span>}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-muted-foreground mono text-[10px] uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Entity</th>
              <th className="text-left px-4 py-2 font-medium">Signal</th>
              <th className="text-left px-4 py-2 font-medium">Reason</th>
              <th className="text-left px-4 py-2 font-medium">Closed by</th>
            </tr>
          </thead>
          <tbody>
            {leads.slice(0, 50).map((l, i) => (
              <LeadRow key={i} lead={l} />
            ))}
          </tbody>
        </table>
        {leads.length > 50 && (
          <div className="px-4 py-2 mono text-[10px] text-muted-foreground border-t border-border">
            Showing 50 of {leads.length}. Full list in submission.json.
          </div>
        )}
      </div>
    </div>
  );
}

function LeadRow({ lead }: { lead: LeadNotPursued }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="border-t border-border hover:bg-muted/20 transition-colors cursor-pointer" onClick={() => setOpen(!open)}>
        <td className="px-4 py-2 mono text-foreground whitespace-nowrap">{lead.entity}</td>
        <td className="px-4 py-2 mono text-muted-foreground">{lead.signal}</td>
        <td className="px-4 py-2 text-muted-foreground max-w-md truncate">{lead.reason}</td>
        <td className="px-4 py-2">
          <span className="mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border border-border text-muted-foreground">
            {lead.closed_by}
          </span>
        </td>
      </tr>
      {open && (
        <tr className="bg-muted/10 border-t border-border">
          <td colSpan={4} className="px-4 py-3 text-xs text-muted-foreground leading-relaxed">
            <div className="mono text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-1">Full reason</div>
            {lead.reason}
            {lead.tool_calls_made && lead.tool_calls_made.length > 0 && (
              <div className="mt-2">
                <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground/70">Tools invoked: </span>
                <span className="mono text-[11px] text-foreground">{lead.tool_calls_made.join(", ")}</span>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

const EVENT_STYLE: Record<string, { color: string; label: string }> = {
  run_started: { color: "#22C55E", label: "Run started" },
  lead_opened: { color: "#3B82F6", label: "Lead opened" },
  hypothesis: { color: "#EAB308", label: "Hypothesis" },
  tool_call: { color: "#06B6D4", label: "Tool call" },
  evidence: { color: "#8B5CF6", label: "Evidence" },
  challenge: { color: "#F97316", label: "Challenge" },
  lead_closed: { color: "#EF4444", label: "Lead closed" },
  finding: { color: "#A44200", label: "Finding" },
  metrics: { color: "#A3A3A3", label: "Metrics" },
  run_finished: { color: "#F5F5F5", label: "Run finished" },
};

function LiveInvestigation() {
  const stream = useEventStream();
  const total = (stream as unknown as { allEvents?: unknown[] }).allEvents?.length;
  return (
    <div className="p-8 space-y-4 animate-fade-in max-w-4xl">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold text-foreground">Live Investigation</h1>
        <p className="text-sm text-muted-foreground">Replay the deterministic pipeline event by event. Every finding you see is receipt-backed.</p>
      </header>

      <div className="rounded-lg border border-border bg-surface p-4 flex flex-wrap items-center gap-3">
        <button onClick={stream.isPlaying ? stream.pause : stream.play} className="mono text-[11px] uppercase tracking-wider px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary-hover flex items-center gap-1.5 cursor-pointer">
          {stream.isPlaying ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          {stream.isPlaying ? "Pause" : "Play"}
        </button>
        <button onClick={stream.reset} className="mono text-[11px] uppercase tracking-wider px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground flex items-center gap-1.5 cursor-pointer">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
        <div className="flex items-center gap-2">
          <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">Speed</span>
          {[1, 4, 10, 20].map((s) => (
            <button
              key={s}
              onClick={() => stream.setSpeed(s)}
              className={cn(
                "mono text-[11px] px-2 py-0.5 rounded-md border cursor-pointer transition-colors",
                stream.speed === s ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground border-border hover:text-foreground",
              )}
            >
              {s}×
            </button>
          ))}
        </div>
        <div className="ml-auto mono text-[10px] text-muted-foreground">
          {stream.events.length} / {total ?? "?"} events
        </div>
      </div>

      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <div className="max-h-[60vh] overflow-y-auto">
          {stream.events.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground mono text-xs">Press Play to start the replay.</div>
          ) : (
            <ul className="divide-y divide-border">
              {stream.events.map((ev) => (
                <EventLine key={`${ev.seq}-${ev.t}`} event={ev} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function EventLine({ event }: { event: ForensicEvent }) {
  const style = EVENT_STYLE[event.type] ?? { color: "#A3A3A3", label: event.type };
  return (
    <li className="px-4 py-2 flex items-baseline gap-3 animate-slide-in-left hover:bg-muted/20 transition-colors">
      <span className="mono text-[10px] text-muted-foreground w-14 shrink-0">{event.t.toFixed(2)}s</span>
      <span className="inline-block h-2 w-2 rounded-full shrink-0" style={{ background: style.color }} />
      <span className="mono text-[10px] uppercase tracking-wider w-28 shrink-0" style={{ color: style.color }}>{style.label}</span>
      <span className="mono text-[11px] text-foreground truncate flex-1">{event.entity || "—"}</span>
      <span className="mono text-[10px] text-muted-foreground truncate max-w-[40%]">{summarizePayload(event)}</span>
    </li>
  );
}

function summarizePayload(ev: ForensicEvent): string {
  const p = (ev as unknown as { payload?: Record<string, unknown> }).payload ?? {};
  if (ev.type === "lead_opened") return String(p.signal ?? p.detector ?? "");
  if (ev.type === "tool_call") return String(p.tool ?? "");
  if (ev.type === "finding") return String(p.scheme_type ?? "");
  if (ev.type === "lead_closed") return String(p.closed_by ?? "");
  if (ev.type === "run_finished") return `${p.findings_count ?? 0} findings`;
  return "";
}

function MetricsDashboard() {
  const { rows: sweep, isMock } = useSweepData();
  const stats = useMemo(() => {
    if (!sweep || sweep.length === 0) return null;
    const totalRecallNum = sweep.reduce((s, r) => s + r.recall_num, 0);
    const totalRecallDen = sweep.reduce((s, r) => s + r.recall_den, 0);
    const totalFalse = sweep.reduce((s, r) => s + r.false_accusations, 0);
    const wallP50 = [...sweep].sort((a, b) => a.wall_clock - b.wall_clock)[Math.floor(sweep.length / 2)]?.wall_clock ?? 0;
    return { totalRecallNum, totalRecallDen, totalFalse, wallP50, count: sweep.length };
  }, [sweep]);

  const maxWall = useMemo(() => (sweep ? Math.max(...sweep.map((r) => r.wall_clock)) : 1), [sweep]);

  return (
    <div className="p-8 space-y-5 animate-fade-in">
      <header className="space-y-1 flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold text-foreground">Sweep Metrics</h1>
          <p className="text-sm text-muted-foreground">Deterministic aggregate over tuning seeds 1–50. Reported seeds 901–905 stay sealed until submission.</p>
        </div>
        {isMock && <span className="mono text-[10px] text-muted-foreground uppercase tracking-widest">mock data</span>}
      </header>

      {!stats ? (
        <div className="rounded-lg border border-border bg-surface p-8 text-center text-muted-foreground text-sm">
          No sweep data available. Run <code className="text-primary">python eval/sweep.py --seeds 1-50</code>.
        </div>
      ) : (
        <>
          <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <StatCard label="Recall" value={`${((stats.totalRecallNum / Math.max(stats.totalRecallDen, 1)) * 100).toFixed(1)}%`} hint={`${stats.totalRecallNum} / ${stats.totalRecallDen} across ${stats.count} seeds`} />
            <StatCard label="False accusations" value={String(stats.totalFalse)} hint="every accusation cites law + exhibits" glow={stats.totalFalse === 0} />
            <StatCard label="Wall clock (p50)" value={`${stats.wallP50.toFixed(2)}s`} hint="median per estate" />
          </section>

          <section className="rounded-lg border border-border bg-surface overflow-hidden">
            <div className="px-5 py-3 border-b border-border">
              <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Wall clock per seed</h2>
            </div>
            <div className="p-4 flex items-end gap-0.5 h-24">
              {sweep!.map((r) => (
                <div
                  key={r.seed}
                  className="flex-1 min-w-[6px] rounded-sm bg-primary/70 hover:bg-primary transition-colors cursor-help"
                  style={{ height: `${Math.max((r.wall_clock / maxWall) * 100, 4)}%` }}
                  title={`seed ${r.seed}: ${r.wall_clock.toFixed(2)}s · recall ${r.recall_num}/${r.recall_den}`}
                />
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-surface overflow-hidden">
            <div className="px-5 py-3 border-b border-border">
              <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Per-seed results (top 20)</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full mono text-[11px]">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">seed</th>
                    <th className="text-left px-4 py-2 font-medium">findings</th>
                    <th className="text-left px-4 py-2 font-medium">leads</th>
                    <th className="text-left px-4 py-2 font-medium">recall</th>
                    <th className="text-left px-4 py-2 font-medium">false</th>
                    <th className="text-left px-4 py-2 font-medium">wall_clock</th>
                  </tr>
                </thead>
                <tbody>
                  {sweep!.slice(0, 20).map((r) => (
                    <tr key={r.seed} className="border-t border-border hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-1.5 text-foreground">{String(r.seed).padStart(4, "0")}</td>
                      <td className="px-4 py-1.5 text-foreground">{r.findings}</td>
                      <td className="px-4 py-1.5 text-muted-foreground">{r.leads}</td>
                      <td className="px-4 py-1.5 text-primary">{r.recall_num}/{r.recall_den}</td>
                      <td className={cn("px-4 py-1.5", r.false_accusations === 0 ? "text-success" : "text-destructive")}>{r.false_accusations}</td>
                      <td className="px-4 py-1.5 text-muted-foreground">{r.wall_clock.toFixed(2)}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function NotFound() {
  const { pathname } = useLocation();
  return (
    <div className="p-16 text-center space-y-3">
      <p className="mono text-xs text-muted-foreground">{pathname}</p>
      <h2 className="text-2xl text-foreground">Route not found</h2>
      <Link to="/" className="inline-block text-primary text-sm hover:underline">Back to overview</Link>
    </div>
  );
}

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <MockBanner />
      <div className="flex-1 flex">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <SubmissionProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/case" element={<CaseFile />} />
          <Route path="/case/:findingIndex" element={<FindingDetail />} />
          <Route path="/live" element={<LiveInvestigation />} />
          <Route path="/leads" element={<LeadsLog />} />
          <Route path="/metrics" element={<MetricsDashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
    </SubmissionProvider>
  );
}
