import { SHOWCASE } from "@/lib/showcase";
import { StatusPanel } from "../status-panel";

export default function SystemPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-[30px] font-semibold leading-9 tracking-tight">System status</h1>
      <p className="mt-2 mb-8 max-w-xl text-muted">
        {SHOWCASE
          ? "This is the static showcase: no API, database or queue runs here. Every page reads a snapshot taken from a real FlightPath stack when the site was built."
          : "Whether the API, database and job queue are reachable right now. Every value comes from a real request; nothing is hardcoded."}
      </p>
      <StatusPanel />
    </main>
  );
}
