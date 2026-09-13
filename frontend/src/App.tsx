import { Routes, Route, Link, useLocation } from "react-router-dom";

function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-2xl w-full space-y-6">
        <header>
          <p className="mono text-xs text-muted-foreground">Team CLAUDIUS MAXIMUS · HackMTY 2026 · Infosys Track</p>
          <h1 className="text-3xl text-foreground mt-2">Forensic Auditor</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Auditor forense automatizado sobre estates SQLite. Consume{" "}
            <code>out/submission.json</code> y <code>out/events.jsonl</code>.
          </p>
        </header>
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <NavCard to="/case" title="Case File" description="Findings, exhibits y money trail" />
          <NavCard to="/live" title="Live Investigation" description="Timeline animado del run" />
          <NavCard to="/metrics" title="Metrics" description="Recall y falsas por seed" />
        </section>
        <footer className="pt-4 border-t border-border text-xs text-muted-foreground mono">
          Scaffold Fase 0 completo. Fase 1 (types + mocks) pendiente.
        </footer>
      </div>
    </main>
  );
}

function NavCard({ to, title, description }: { to: string; title: string; description: string }) {
  return (
    <Link
      to={to}
      className="block rounded-lg border border-border bg-card p-4 shadow-sm hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
    >
      <h3 className="text-foreground font-semibold text-base">{title}</h3>
      <p className="text-xs text-muted-foreground mt-1">{description}</p>
    </Link>
  );
}

function Placeholder() {
  const { pathname } = useLocation();
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-3">
        <p className="mono text-xs text-muted-foreground">{pathname}</p>
        <h2 className="text-2xl text-foreground">Vista pendiente</h2>
        <p className="text-sm text-muted-foreground">
          Esta ruta se implementa en Fase 2-5 del plan de frontend.
        </p>
        <Link to="/" className="inline-block text-primary text-sm hover:underline">
          Volver al inicio
        </Link>
      </div>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/case" element={<Placeholder />} />
      <Route path="/case/:findingIndex" element={<Placeholder />} />
      <Route path="/live" element={<Placeholder />} />
      <Route path="/leads" element={<Placeholder />} />
      <Route path="/metrics" element={<Placeholder />} />
      <Route path="/about" element={<Placeholder />} />
      <Route path="*" element={<Placeholder />} />
    </Routes>
  );
}
