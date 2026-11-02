import { ErrorPanel, PageHead } from "@/components/ui";
import { publicBackendUrl, tryApi } from "@/lib/backend";
import { getSession } from "@/lib/session";
import type { Segments } from "@/lib/types";
import { GrowthBoard } from "./GrowthBoard";

export const metadata = { title: "Growth" };

export default async function Growth() {
  const session = await getSession();
  const segments = await tryApi<Segments>("/v1/growth/segments");
  if (!segments.data) return <><PageHead title="Growth" /><ErrorPanel message={segments.error ?? "Couldn't load this page."} /></>;
  return (
    <>
      <PageHead title="Growth" sub="Who is most likely to buy what you sell, and how to reach them. Your rep never messages anyone who hasn't come to you first." />
      <GrowthBoard initial={segments.data} chatUrl={`${publicBackendUrl()}/chat/${session?.tenant ?? ""}`} isAdmin={session?.role === "admin"} />
    </>
  );
}
