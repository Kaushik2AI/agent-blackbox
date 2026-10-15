import { StatusPanel } from "../status-panel";

export default function SystemPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight">System status</h1>
      <p className="mt-2 mb-8 max-w-xl text-sm leading-6 text-muted">
        Live connectivity from this page to the FastAPI backend and its dependencies. Every value
        comes from a real request; nothing is hardcoded.
      </p>
      <StatusPanel />
    </main>
  );
}
