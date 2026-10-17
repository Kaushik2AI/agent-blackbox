import { ReplayStudio } from "@/components/replay-studio";
import { runParams } from "@/lib/showcase-params";

// Static showcase: pre-render every recorded run (empty in a normal build).
export function generateStaticParams() {
  return runParams();
}

export default async function ReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReplayStudio id={id} />;
}
