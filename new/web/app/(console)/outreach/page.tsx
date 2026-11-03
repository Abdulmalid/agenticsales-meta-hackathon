import { ErrorPanel, Notice, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import type { OutreachState } from "@/lib/types";
import { OutreachBoard } from "./OutreachBoard";

export const metadata = { title: "Outreach" };

export default async function Outreach() {
  const { data, error } = await tryApi<OutreachState>("/v1/outreach");
  return (
    <>
      <PageHead title="Cold email outreach" sub="Write a short personal email to people who may want what you sell. You read and approve every email before it goes." />
      <div style={{ marginBottom: "1rem" }}>
        <Notice tone="info">
          <strong>What this is for.</strong> Your rep normally answers customers who message you. Outreach is the other direction: finding new customers. You give it a
          list of businesses or people you have a lawful reason to email (a Google Sheet or a pasted list), you describe your ideal customer, and your rep scores each
          person against that, sets aside the poor fits, and writes a short personal email for the good ones. <strong>You</strong> run it and approve every email; the rep
          does the reading and writing. Nothing is ever sent without your approval, and it goes out only Monday to Saturday, 8am to 6pm, within your daily limit. A reply
          is marked here, and anyone who asks to stop is never emailed again. You can ignore this page if you only sell to people who contact you first.
        </Notice>
      </div>
      {error || !data ? <ErrorPanel message={error ?? "Could not load outreach."} /> : <OutreachBoard initial={data} />}
    </>
  );
}
