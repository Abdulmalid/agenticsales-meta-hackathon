import { ErrorPanel, PageHead, Stat } from "@/components/ui";
import { Icon } from "@/components/icons";
import { tryApi } from "@/lib/backend";
import { getSession } from "@/lib/session";
import { naira } from "@/lib/format";
import type { Books } from "@/lib/types";
import { ExpenseBook } from "./ExpenseBook";

export const metadata = { title: "Books" };

export default async function BooksPage() {
  const session = await getSession();
  const books = await tryApi<Books>("/v1/books");
  if (!books.data) return <><PageHead title="Books" /><ErrorPanel message={books.error ?? "Couldn't load your books."} /></>;
  const b = books.data;
  return (
    <>
      <PageHead title="Books" sub="Money in is what the payment gateway confirmed. Money out is what you tell your rep: text or send a voice note to your business bot, for example “spent 5k on transport”." />
      <div className="grid g4" style={{ marginBottom: "1rem" }}>
        <Stat label="Money in today" value={naira(b.today.revenue_kobo)} icon={<Icon name="money" />} hint="confirmed payments only" />
        <Stat label="Spent today" value={naira(b.today.expenses_kobo)} icon={<Icon name="receipt" />} />
        <Stat label="Profit this week" value={naira(b.week.profit_kobo)} icon={<Icon name="analytics" />} hint={`${naira(b.week.revenue_kobo)} in · ${naira(b.week.expenses_kobo)} out`} />
        <Stat label="Profit this month" value={naira(b.month.profit_kobo)} icon={<Icon name="target" />} hint={`${naira(b.month.revenue_kobo)} in · ${naira(b.month.expenses_kobo)} out`} />
      </div>
      <ExpenseBook recent={b.recent} categories={b.month.by_category} isAdmin={session?.role === "admin"} />
    </>
  );
}
