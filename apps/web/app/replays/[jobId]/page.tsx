import { ComparisonView } from "@/components/comparison-view";
import { replayParams } from "@/lib/showcase-params";

// Static showcase: pre-render every recorded run (empty in a normal build).
export function generateStaticParams() {
  return replayParams();
}

export default async function ComparisonPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  return <ComparisonView jobId={jobId} />;
}
