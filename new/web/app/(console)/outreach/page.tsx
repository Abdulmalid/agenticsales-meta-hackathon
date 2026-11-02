import { ErrorPanel, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import type { OutreachState } from "@/lib/types";
import { OutreachBoard } from "./OutreachBoard";

export const metadata = { title: "Outreach" };

export default async function Outreach() {
  const { data, error } = await tryApi<OutreachState>("/v1/outreach");
  return (
    <>
      <PageHead title="Cold email outreach" sub="Write a short personal email to people who may want what you sell. You read and approve every email before it goes." />
      {error || !data ? <ErrorPanel message={error ?? "Could not load outreach."} /> : <OutreachBoard initial={data} />}
    </>
  );
}
