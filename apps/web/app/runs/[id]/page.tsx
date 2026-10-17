import { RunView } from "@/components/run-view";
import { runParams } from "@/lib/showcase-params";

// Static showcase: pre-render every recorded run (empty in a normal build).
export function generateStaticParams() {
  return runParams();
}

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunView id={id} />;
}
