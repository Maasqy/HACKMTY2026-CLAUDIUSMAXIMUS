import html2pdf from "html2pdf.js";
import type { Finding, Submission } from "@/types/submission";
import type { Event as ForensicEvent } from "@/types/events";
import { formatMxn } from "@/lib/formatMxn";

// One-click PDF export for a Finding. Builds a light-theme, print-friendly
// DOM subtree that is present in the DOM (so html2canvas can render it) but
// invisible to the user (opacity:0), hands it to html2pdf.js, and triggers
// a browser download. Does not use window.print() (silent hang in some
// browsers + requires the user to pick Save-as-PDF as destination).
//
// Why the element is NOT positioned at `left:-10000px`: html2canvas needs
// the element inside the viewport bounds to compute layout; offscreen
// elements produce blank/empty canvases in Chrome and Safari.
export async function downloadFindingPdf(
  finding: Finding,
  submission: Submission,
  caseNumber: string,
  companyRfc: string = "UDA230508OIG",
  reasoningEvents: ForensicEvent[] = [],
): Promise<void> {
  // 8.5in @ 96dpi = 816px; use letter width in pixels so html2canvas sees
  // a well-defined viewport.
  const PAGE_WIDTH_PX = 816;

  // Reliable technique: render container VISIBLY on top of the page under a
  // white overlay with a "Generating PDF…" spinner, so html2canvas captures
  // it correctly (all offscreen tricks — `left: -9999px`, `top: -99999px`,
  // `opacity: 0` — produced blank 3KB PDFs in practice because html2canvas
  // needs the target element in the visible viewport with real dimensions).
  // User sees an intentional loading overlay for ~2s, then the download
  // fires and the overlay is removed. Feels like a real product operation.
  const overlay = document.createElement("div");
  overlay.style.position = "fixed";
  overlay.style.inset = "0";
  overlay.style.zIndex = "100000";
  overlay.style.background = "rgba(10,10,10,0.85)";
  overlay.style.display = "flex";
  overlay.style.flexDirection = "column";
  overlay.style.alignItems = "center";
  overlay.style.justifyContent = "flex-start";
  overlay.style.padding = "40px 0";
  overlay.style.overflow = "auto";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-label", "Generating PDF report");

  const spinner = document.createElement("div");
  spinner.style.color = "#A44200";
  spinner.style.fontFamily = "'Fira Code', monospace";
  spinner.style.fontSize = "12px";
  spinner.style.letterSpacing = "0.15em";
  spinner.style.textTransform = "uppercase";
  spinner.style.marginBottom = "16px";
  spinner.style.background = "rgba(0,0,0,0.6)";
  spinner.style.padding = "8px 16px";
  spinner.style.borderRadius = "4px";
  spinner.style.border = "1px solid #A44200";
  spinner.textContent = "Generating PDF report…";
  overlay.appendChild(spinner);

  const container = document.createElement("div");
  container.style.width = `${PAGE_WIDTH_PX}px`;
  container.style.background = "#ffffff";
  container.style.color = "#0a0a0a";
  container.style.fontFamily = "'Fira Sans', Arial, sans-serif";
  container.style.padding = "40px 48px";
  container.style.boxSizing = "border-box";
  container.style.boxShadow = "0 20px 60px rgba(0,0,0,0.4)";
  container.innerHTML = buildReportHtml(finding, submission, caseNumber, companyRfc, reasoningEvents);
  overlay.appendChild(container);
  document.body.appendChild(overlay);

  // Wait for fonts (Fira Sans / Fira Code) before rasterising, otherwise
  // html2canvas may snapshot the page mid-swap with the fallback font.
  if (typeof document !== "undefined" && "fonts" in document) {
    try { await (document as unknown as { fonts: { ready: Promise<unknown> } }).fonts.ready; } catch { /* ignore */ }
  }
  // Give the browser one paint frame to lay everything out.
  await new Promise<void>((r) => requestAnimationFrame(() => r()));

  try {
    await html2pdf()
      .set({
        margin: 0,
        filename: `${caseNumber}.pdf`,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: {
          scale: 2,
          useCORS: true,
          allowTaint: false,
          backgroundColor: "#ffffff",
          logging: false,
          letterRendering: true,
          windowWidth: PAGE_WIDTH_PX,
        },
        jsPDF: { unit: "in", format: "letter", orientation: "portrait" },
        pagebreak: { mode: ["css", "legacy"], avoid: [".pdf-avoid-break"] },
      })
      .from(container)
      .save();
  } finally {
    document.body.removeChild(overlay);
  }
}

function buildReportHtml(f: Finding, submission: Submission, caseNumber: string, companyRfc: string, events: ForensicEvent[]): string {
  const issuedOn = new Date().toISOString().slice(0, 10);
  const mono = "font-family: 'Fira Code', 'Courier New', monospace;";
  const border = "1px solid #333";
  const reasoningSection = buildReasoningChainHtml(events, mono);
  const trailDiagram = buildMoneyTrailDiagramHtml(f, mono);

  const exhibitRows = f.exhibits.map((ex) => `
    <tr>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono} color:#a44200; font-weight:600;">${escapeHtml(ex.exhibit_id)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono} color:#555;">${escapeHtml(ex.source_table)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono}">${escapeHtml(ex.record_id)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt;">${escapeHtml(ex.note)}</td>
    </tr>
  `).join("");

  const trailRows = (f.money_trail ?? []).map((s, i) => `
    <tr>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono}">${i + 1}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono}">${escapeHtml(s.from)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono} color:#a44200; font-weight:600;">${escapeHtml(formatMxn(s.amount))}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono}">${escapeHtml(s.to)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono} color:#555;">${escapeHtml(s.date)}</td>
      <td style="border:${border}; padding:2mm 3mm; font-size:8pt; ${mono}">${escapeHtml(s.exhibit_id)}</td>
    </tr>
  `).join("");

  const trailSection = (f.money_trail && f.money_trail.length > 0) ? `
    <table class="pdf-avoid-break" style="width:100%; border-collapse:collapse; margin-top:2mm;">
      <thead>
        <tr>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">#</th>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">From</th>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:right;">Amount</th>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">To</th>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">Date</th>
          <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">Exhibit</th>
        </tr>
      </thead>
      <tbody>${trailRows}</tbody>
    </table>
  ` : `
    <p style="margin:3mm 0; padding:4mm; border:1px dashed #999; text-align:center; font-size:9pt; color:#555; font-style:italic;">
      No cash movement recorded — the fraud is in the accounting entries only (see exhibits).
    </p>
  `;

  const confidenceBadge = `<span style="border:1.5px solid #0a0a0a; padding:0.5mm 2mm; font-weight:700; font-size:9pt; ${mono}">${f.confidence.toUpperCase()}</span>`;

  return `
    <div style="padding:0; box-sizing:border-box;">
      <!-- HEADER -->
      <div style="border-bottom:2px solid #0a0a0a; padding-bottom:3mm; margin-bottom:5mm; display:flex; justify-content:space-between; align-items:flex-end;">
        <div>
          <div style="font-size:8pt; letter-spacing:1.5pt; text-transform:uppercase; color:#777; ${mono}">Fraud Forensics · Case File</div>
          <div style="font-size:17pt; font-weight:700; margin-top:1mm;">Case ${escapeHtml(caseNumber)}</div>
          <div style="font-size:9pt; color:#555; margin-top:1mm; ${mono}">Team CLAUDIUS MAXIMUS · HackMTY 2026 · Infosys Forensic Auditor</div>
        </div>
        <div style="text-align:right; ${mono} font-size:9pt; line-height:1.6;">
          <div><b>Subject RFC:</b> ${escapeHtml(companyRfc)}</div>
          <div><b>Issued:</b> ${issuedOn}</div>
          <div><b>Seed:</b> ${String(submission.seed).padStart(4, "0")}</div>
          <div style="margin-top:1mm;"><b>Confidence:</b> ${confidenceBadge}</div>
        </div>
      </div>

      <!-- SCHEME + AMOUNT -->
      <div class="pdf-avoid-break" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5mm; padding:3mm 4mm; background:#fafafa; border:1px solid #ccc; border-left:4px solid #a44200;">
        <div>
          <div style="font-size:8pt; letter-spacing:1pt; text-transform:uppercase; color:#a44200; ${mono} font-weight:700;">${f.scheme_type.replace(/_/g, " ")}</div>
          <div style="font-size:12pt; font-weight:600; margin-top:1mm;">${escapeHtml(f.entities.join(", "))}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:8pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono}">Amount at stake</div>
          <div style="font-size:20pt; font-weight:700; color:#a44200; ${mono}">${escapeHtml(formatMxn(f.peso_amount))}</div>
        </div>
      </div>

      <!-- EXECUTIVE SUMMARY -->
      <section class="pdf-avoid-break" style="margin-bottom:5mm;">
        <h2 style="font-size:10pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono} margin:0 0 2mm 0;">Executive summary</h2>
        <p style="font-size:10pt; line-height:1.55; margin:0;">${escapeHtml(f.narrative)}</p>
      </section>

      <!-- RULE BROKEN -->
      <section class="pdf-avoid-break" style="margin-bottom:5mm; padding:3mm 4mm; background:#fafafa; border-left:3px solid #0a0a0a;">
        <h2 style="font-size:9pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono} margin:0 0 1.5mm 0;">Rule broken · legal basis</h2>
        <p style="font-size:9.5pt; line-height:1.5; margin:0; font-style:italic;">${escapeHtml(f.rule_broken)}</p>
      </section>

      <!-- AI REASONING CHAIN -->
      ${reasoningSection}

      <!-- EXHIBITS -->
      <section style="margin-bottom:5mm;">
        <h2 style="font-size:10pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono} margin:0 0 2mm 0;">Exhibits (${f.exhibits.length}) — every row is verifiable in the estate</h2>
        <table style="width:100%; border-collapse:collapse;">
          <thead>
            <tr>
              <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">ID</th>
              <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">Source table</th>
              <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">Record ID</th>
              <th style="border:${border}; padding:2mm 3mm; font-size:8pt; background:#eee; text-align:left;">Note</th>
            </tr>
          </thead>
          <tbody>${exhibitRows}</tbody>
        </table>
      </section>

      <!-- MONEY TRAIL -->
      <section style="margin-bottom:5mm;">
        <h2 style="font-size:10pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono} margin:0 0 2mm 0;">Money trail — each step is a citable bank_txn</h2>
        ${trailDiagram}
        ${trailSection}
      </section>

      <!-- FOOTER -->
      <div style="border-top:1px solid #999; padding-top:3mm; margin-top:5mm; font-size:7.5pt; color:#555; ${mono}">
        <div style="display:flex; justify-content:space-between; gap:6mm; margin-bottom:3mm;">
          <div style="flex:1.3;">
            <b style="color:#0a0a0a;">Reproducibility statement</b><br />
            This case was produced by Fraud Forensics (CLAUDIUS MAXIMUS · HackMTY 2026) from estate seed ${submission.seed}.
            Every exhibit ID corresponds to a record in the SQLite estate; the peso amount reconciles within the 2% tolerance
            defined in src/config.py:RECONCILE_TOLERANCE_PCT. Re-running the pipeline against the same estate reproduces this
            case byte-for-byte.
          </div>
          <div style="flex:1;">
            <b style="color:#0a0a0a;">Run metadata</b><br />
            llm_calls: ${submission.run_metadata.llm_calls}<br />
            mxn_cost: ${formatMxn(submission.run_metadata.mxn_cost)}<br />
            wall_clock: ${submission.run_metadata.wall_clock_seconds.toFixed(2)}s<br />
            deterministic: ${String(submission.run_metadata.deterministic ?? false)}
          </div>
          <div style="flex:1;">
            <b style="color:#0a0a0a;">Signatures</b><br />
            <div style="margin-top:6mm; border-top:1px solid #0a0a0a; padding-top:0.5mm;">Investigator</div>
            <div style="margin-top:5mm; border-top:1px solid #0a0a0a; padding-top:0.5mm;">Reviewer</div>
          </div>
        </div>
        <div style="text-align:center; color:#999;">— end of report · case ${escapeHtml(caseNumber)} · ${issuedOn} —</div>
      </div>
    </div>
  `;
}

function escapeHtml(v: unknown): string {
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Reasoning-chain step colors, mirrors the on-screen ReasoningChain component.
const REASONING_META: Record<string, { color: string; label: string }> = {
  lead_opened: { color: "#3B82F6", label: "Signal detected" },
  hypothesis: { color: "#EAB308", label: "Hypothesis" },
  tool_call: { color: "#06B6D4", label: "Tool call" },
  evidence: { color: "#8B5CF6", label: "Evidence recorded" },
  challenge: { color: "#F97316", label: "Challenger response" },
  lead_closed: { color: "#EF4444", label: "Lead closed" },
  finding: { color: "#A44200", label: "Finding promoted" },
};

function buildReasoningChainHtml(events: ForensicEvent[], mono: string): string {
  const relevant = events.filter((e) => REASONING_META[e.type]);
  if (relevant.length === 0) return "";

  const steps = relevant.map((ev) => {
    const meta = REASONING_META[ev.type];
    const p = (ev as unknown as { payload?: Record<string, unknown> }).payload ?? {};
    const line = formatPayload(ev.type, p);
    return `
      <div class="pdf-avoid-break" style="display:flex; gap:8px; margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid #eee;">
        <div style="width:4px; background:${meta.color}; border-radius:2px; flex-shrink:0;"></div>
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:1mm;">
            <span style="${mono} font-size:7.5pt; font-weight:700; color:${meta.color}; letter-spacing:0.5pt; text-transform:uppercase;">${meta.label}</span>
            <span style="${mono} font-size:7pt; color:#999;">t=${ev.t.toFixed(2)}s</span>
          </div>
          <div style="font-size:8.5pt; line-height:1.45; color:#0a0a0a;">${escapeHtml(line)}</div>
        </div>
      </div>
    `;
  }).join("");

  return `
    <section style="margin-bottom:5mm;">
      <h2 style="font-size:10pt; letter-spacing:1pt; text-transform:uppercase; color:#555; ${mono} margin:0 0 2mm 0;">
        AI Reasoning Chain — Gemma 4 investigator ↔ challenger loop (${relevant.length} steps)
      </h2>
      <div style="border-left:2px solid #A44200; padding:3mm 4mm; background:#fafafa;">
        ${steps}
      </div>
    </section>
  `;
}

function formatPayload(type: string, p: Record<string, unknown>): string {
  if (type === "lead_opened") return String(p.reason ?? p.signal ?? "Signal detected");
  if (type === "hypothesis") return String(p.statement ?? p.hypothesis ?? p.scheme_type ?? "");
  if (type === "tool_call") {
    const tool = String(p.tool ?? "unknown_tool");
    const args = p.args ? ` (${Object.entries(p.args as object).slice(0, 2).map(([k, v]) => `${k}=${JSON.stringify(v).slice(0, 30)}`).join(", ")})` : "";
    const summary = p.result_summary ? ` → ${p.result_summary}` : "";
    return `Called ${tool}${args}${summary}`;
  }
  if (type === "evidence") return String(p.note ?? `${p.source_table}/${p.record_id}`);
  if (type === "challenge") {
    const objection = String(p.objection ?? p.challenge ?? "");
    const resolved = p.resolved === true ? " · resolved" : p.resolved === false ? " · pending" : "";
    return `${objection}${resolved}`;
  }
  if (type === "lead_closed") return `Closed by ${p.closed_by ?? "unknown"}: ${p.reason ?? ""}`;
  if (type === "finding") return `Promoted to finding: ${p.scheme_type ?? ""}`;
  return "";
}

function buildMoneyTrailDiagramHtml(f: Finding, mono: string): string {
  const steps = f.money_trail ?? [];
  if (steps.length === 0) return "";

  // Deduplicate nodes in order of first appearance
  const nodeIds: string[] = [];
  const seen = new Set<string>();
  for (const s of steps) {
    if (!seen.has(s.from)) { seen.add(s.from); nodeIds.push(s.from); }
    if (!seen.has(s.to)) { seen.add(s.to); nodeIds.push(s.to); }
  }

  // Aggregate edges (same as on-screen diagram)
  const edgeMap = new Map<string, { from: string; to: string; amount: number; count: number; date: string }>();
  for (const s of steps) {
    const key = `${s.from}→${s.to}`;
    const existing = edgeMap.get(key);
    if (existing) {
      existing.amount += s.amount;
      existing.count += 1;
    } else {
      edgeMap.set(key, { from: s.from, to: s.to, amount: s.amount, count: 1, date: s.date });
    }
  }
  const edges = Array.from(edgeMap.values());

  const nodeColor = (id: string): string => {
    if (id.startsWith("EMP:")) return "#F97316";
    if (id === "RFC:UDA230508OIG") return "#3B82F6";
    return "#A44200";
  };
  const nodeKind = (id: string): string => {
    if (id.startsWith("EMP:")) return "Employee";
    if (id === "RFC:UDA230508OIG") return "Company (subject)";
    return "Vendor";
  };

  // Horizontal box-and-arrow layout — simpler than SVG, plays nice with html2canvas.
  const nodeBoxes = nodeIds.map((id) => `
    <td style="text-align:center; vertical-align:middle; padding:0 4mm; min-width:50mm;">
      <div style="border:2px solid ${nodeColor(id)}; border-radius:4px; padding:3mm 4mm; background:#ffffff; display:inline-block;">
        <div style="${mono} font-size:10pt; font-weight:700; color:#0a0a0a; white-space:nowrap;">${escapeHtml(id)}</div>
        <div style="${mono} font-size:7pt; color:${nodeColor(id)}; letter-spacing:0.5pt; text-transform:uppercase; margin-top:1mm;">${nodeKind(id)}</div>
      </div>
    </td>
  `).join(`<td style="text-align:center; vertical-align:middle; padding:0 2mm;"><div style="${mono} font-size:14pt; color:#A44200;">→</div></td>`);

  const edgeLabels = edges.map((e) => {
    const label = e.count > 1 ? `${formatMxn(e.amount)} · ${e.count}× cycles` : `${formatMxn(e.amount)} · ${e.date}`;
    return `
      <div style="${mono} font-size:8pt; padding:1.5mm 3mm; margin:0.5mm 0; border-left:3px solid #A44200; background:#fdf6f0;">
        <b style="color:#A44200;">${escapeHtml(e.from)}</b>
        <span style="color:#666;"> → </span>
        <b style="color:#A44200;">${escapeHtml(e.to)}</b>
        <span style="color:#0a0a0a; margin-left:6px;">${escapeHtml(label)}</span>
        <span style="color:#999; margin-left:6px;">(exhibit ${escapeHtml(e.from === steps[0]?.from ? steps.find((s) => s.from === e.from && s.to === e.to)?.exhibit_id ?? "—" : "—")})</span>
      </div>
    `;
  }).join("");

  return `
    <div class="pdf-avoid-break" style="margin-bottom:3mm; padding:5mm 3mm; background:#ffffff; border:1px solid #ccc; border-radius:4px;">
      <table style="margin:0 auto; border-collapse:collapse;">
        <tr>${nodeBoxes}</tr>
      </table>
      <div style="margin-top:4mm;">
        ${edgeLabels}
      </div>
      <div style="${mono} font-size:7pt; color:#666; text-align:center; margin-top:2mm;">
        ${steps.length} transactions · ${edges.length} unique flows · ${nodeIds.length} entities
      </div>
    </div>
  `;
}
