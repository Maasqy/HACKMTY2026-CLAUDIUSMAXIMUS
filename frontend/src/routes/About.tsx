import { Cpu, Brain, TreePine, ShieldCheck, Scale, GitBranch, Zap, Lock } from "lucide-react";

export default function About() {
  return (
    <div className="p-8 space-y-6 animate-fade-in max-w-4xl">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold text-foreground">How Fraud Forensics works</h1>
        <p className="text-sm text-muted-foreground">
          A three-layer forensic pipeline that never accuses without evidence. Built for HackMTY 2026 by team CLAUDIUS MAXIMUS.
        </p>
      </header>

      <section className="rounded-lg border border-primary/30 bg-surface p-6 shadow-glow">
        <div className="flex items-start gap-3 mb-4">
          <ShieldCheck className="h-6 w-6 text-primary shrink-0 mt-0.5" />
          <div>
            <h2 className="text-xl font-semibold text-foreground">Why zero false accusations matters</h2>
            <p className="text-sm text-muted-foreground mt-1">
              The Infosys rubric penalizes a false accusation exactly as harshly as a missed fraud. Every estate ships up to ten &quot;decoys&quot; — entities that trip a detector but are clean. Our design rule: when in doubt, close the lead with a written reason. The result is 76% recall with <span className="text-primary font-semibold">0 innocents flagged</span> across 50 tuning seeds.
            </p>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <StageCard
          step={1}
          icon={Zap}
          title="Deterministic detectors"
          subtitle="src/detectors/"
          body="Rule-based signals over the eight ledgers: SAT 69-B match, threshold splitting, payment-without-invoice, round-tripping, kickback linkage. Emit leads, never accusations. Same seed → same signals, byte-for-byte."
        />
        <StageCard
          step={2}
          icon={TreePine}
          title="ML lead scorer (CART)"
          subtitle="src/scoring/"
          body="A gradient-boosted decision tree trained on 50 seeds of labeled leads ranks which signals deserve investigation. Ships as a serialized model file — no training happens at inference time, so runs stay deterministic."
        />
        <StageCard
          step={3}
          icon={Brain}
          title="Gemma 4 investigator"
          subtitle="src/forensic/"
          body="Google Gemma 4 (via LM Studio) drives an investigator ↔ challenger loop: hypothesis, tool calls to gather evidence, self-critique, and closing decision. Every call is cached to disk so the same estate replays without network."
        />
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <div className="flex items-start gap-2 mb-3">
          <GitBranch className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Investigator / Challenger / Validator</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div>
            <div className="mono text-[10px] uppercase tracking-wider text-[#3B82F6] mb-1">Investigator</div>
            <p className="text-muted-foreground leading-relaxed">
              Reads the lead, forms a hypothesis, calls typed tools over the estate to gather citable evidence. Every tool result carries a <code>record_id</code>.
            </p>
          </div>
          <div>
            <div className="mono text-[10px] uppercase tracking-wider text-[#F97316] mb-1">Challenger</div>
            <p className="text-muted-foreground leading-relaxed">
              Adversarial second pass. Asks: is materiality proven? Is the vendor exonerated? Is the money trail complete? Forces the investigator to either strengthen or drop the claim.
            </p>
          </div>
          <div>
            <div className="mono text-[10px] uppercase tracking-wider text-[#A44200] mb-1">Validator</div>
            <p className="text-muted-foreground leading-relaxed">
              Pure Python. Reconciles peso amounts within 2%, checks every <code>record_id</code> exists, verifies the rule cited is a real statute (not a statistical outlier). Kills any finding that fails.
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <div className="flex items-start gap-2 mb-3">
          <Scale className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">The rule of law, encoded</h2>
        </div>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li className="flex gap-2"><span className="text-primary">▸</span><span><span className="text-foreground">SAT Art. 69-B CFF</span> — retroactive nullification of CFDIs from listed shell taxpayers. Powers phantom_vendor findings.</span></li>
          <li className="flex gap-2"><span className="text-primary">▸</span><span><span className="text-foreground">NIF A-2</span> — Mexican GAAP substance-over-form principle. Grounds materiality tests.</span></li>
          <li className="flex gap-2"><span className="text-primary">▸</span><span><span className="text-foreground">Internal approval limits</span> — every threshold_splitting finding cites the exact MXN limit and the constant name in <code className="text-primary">src/config.py</code>.</span></li>
          <li className="flex gap-2"><span className="text-primary">▸</span><span><span className="text-foreground">No statistical outliers as evidence</span> — the validator rejects any finding whose <code>rule_broken</code> reads like an anomaly score.</span></li>
        </ul>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-lg border border-border bg-surface p-5">
          <div className="flex items-start gap-2 mb-2">
            <Cpu className="h-4 w-4 text-primary shrink-0 mt-0.5" />
            <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Determinism &amp; replay</h2>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Every LLM call is cached to <code className="text-primary">.llm_cache/</code> keyed by prompt hash. Turn off Wi-Fi and the run reproduces byte-for-byte from the same seed. Judges can verify a specific finding without paying for compute.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface p-5">
          <div className="flex items-start gap-2 mb-2">
            <Lock className="h-4 w-4 text-primary shrink-0 mt-0.5" />
            <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground">Ground-truth isolation</h2>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            The string <code>ground_truth</code> never appears under <code>src/</code>. Estate generator lives in <code>estate_gen/</code>, eval harness in <code>eval/</code> — neither is imported by the pipeline. Judges grep for it as a first sanity check.
          </p>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground mb-3">The three numbers, always</h2>
        <div className="grid grid-cols-3 gap-3">
          <NumberRow label="llm_calls" hint="how many Gemma 4 calls this run made" />
          <NumberRow label="mxn_cost" hint="cost in Mexican pesos at current rate" />
          <NumberRow label="wall_clock_seconds" hint="end-to-end runtime" />
        </div>
        <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
          Every run reports these three numbers in <code className="text-primary">run_metadata</code>. If they are zero, this build ran without the LLM investigator (deterministic-only mode) — still valid, but the reasoning chain will be shorter. Run the pipeline with Gemma 4 enabled to see the full investigator/challenger trail.
        </p>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="mono text-[10px] uppercase tracking-widest text-muted-foreground mb-3">Stack</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <StackBadge label="Python 3.11" hint="pipeline" />
          <StackBadge label="Gemma 4" hint="LLM investigator" />
          <StackBadge label="SQLite" hint="estate storage" />
          <StackBadge label="scikit-learn" hint="CART scorer" />
          <StackBadge label="Vite + React 18" hint="this UI" />
          <StackBadge label="TypeScript" hint="strict mode" />
          <StackBadge label="Tailwind CSS" hint="design system" />
          <StackBadge label="sql.js (WASM)" hint="in-browser CSV → SQLite" />
        </div>
      </section>
    </div>
  );
}

function StageCard({ step, icon: Icon, title, subtitle, body }: { step: number; icon: typeof Cpu; title: string; subtitle: string; body: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5 space-y-2">
      <div className="flex items-center justify-between">
        <div className="w-8 h-8 rounded-full bg-primary/15 border border-primary/40 flex items-center justify-center">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        <span className="mono text-[10px] uppercase tracking-wider text-muted-foreground">Step {step}</span>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <div className="mono text-[10px] text-primary/70 mt-0.5">{subtitle}</div>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">{body}</p>
    </div>
  );
}

function NumberRow({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="rounded-md border border-border bg-background/50 p-3">
      <div className="mono text-[11px] text-primary">{label}</div>
      <div className="mono text-[10px] text-muted-foreground mt-1 leading-relaxed">{hint}</div>
    </div>
  );
}

function StackBadge({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="rounded-md border border-border bg-background/50 px-3 py-2">
      <div className="mono text-xs text-foreground">{label}</div>
      <div className="mono text-[10px] text-muted-foreground mt-0.5">{hint}</div>
    </div>
  );
}
