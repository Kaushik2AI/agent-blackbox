import { StatusPanel } from "./status-panel";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <header className="mb-10">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted">
          Agent BlackBox · M1
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">System status</h1>
        <p className="mt-3 max-w-xl text-sm leading-6 text-muted">
          Live connectivity from this page to the FastAPI backend and its dependencies. Every
          value below comes from a real request; nothing is hardcoded.
        </p>
      </header>
      <StatusPanel />
      <footer className="mt-12 border-t border-line pt-6 text-xs leading-5 text-muted">
        Not built yet: run ingestion (M3), trace inspector (M4), failure analysis (M5), and
        replay (M6–M7). Those screens will appear when the backend can actually serve them.
      </footer>
    </main>
  );
}
