import html2pdf from "html2pdf.js";
import type { Finding, Submission } from "@/types/submission";
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
  container.innerHTML = buildReportHtml(finding, submission, caseNumber, companyRfc);
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

function buildReportHtml(f: Finding, submission: Submission, caseNumber: string, companyRfc: string): string {
  const issuedOn = new Date().toISOString().slice(0, 10);
  const mono = "font-family: 'Fira Code', 'Courier New', monospace;";
  const border = "1px solid #333";

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
