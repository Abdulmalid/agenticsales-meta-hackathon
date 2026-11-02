import { ErrorPanel, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import type { TeamMember } from "@/lib/types";
import { TeamBoard } from "./TeamBoard";

export const metadata = { title: "Team" };

export default async function TeamPage() {
  const team = await tryApi<TeamMember[]>("/v1/team");
  if (!team.data) return <><PageHead title="Team" /><ErrorPanel message={team.error ?? "Couldn't load your team."} /></>;
  return (
    <>
      <PageHead title="Team" sub="The people who can sign in to your console. Give each person their own token so you can see who did what." />
      <TeamBoard members={team.data} />
    </>
  );
}
