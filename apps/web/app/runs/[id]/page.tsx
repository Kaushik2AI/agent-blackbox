import { Inspector } from "@/components/inspector";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Inspector id={id} />;
}
