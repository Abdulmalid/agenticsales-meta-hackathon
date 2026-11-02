import { ErrorPanel, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import type { HistoryPage } from "@/lib/types";
import { HistoryFeed } from "./HistoryFeed";

export const metadata = { title: "History" };

export default async function History() {
  const first = await tryApi<HistoryPage>("/v1/history?limit=100");
  if (!first.data) return <><PageHead title="History" /><ErrorPanel message={first.error ?? "Couldn't load the history."} /></>;
  return (
    <>
      <PageHead title="History" sub="Every sale, stock change, delivery update and decision, with the time to the second. It is read straight from your records, so it always matches your orders and stock." />
      <HistoryFeed initial={first.data} />
    </>
  );
}
