import { ComparisonView } from "@/components/comparison-view";

export default async function ComparisonPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  return <ComparisonView jobId={jobId} />;
}
