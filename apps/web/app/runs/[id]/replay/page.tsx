import { ReplayStudio } from "@/components/replay-studio";

export default async function ReplayPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReplayStudio id={id} />;
}
