import Link from "next/link";
import { naira } from "@/lib/format";
import type { ShiftReport } from "@/lib/types";

const WINDOWS: [number, string][] = [[12, "12 hours"], [24, "24 hours"], [168, "7 days"]];
const ALERT_LABEL: Record<string, string> = {
  discount: "discount request", order: "large order", fraud_review: "payment to check", human_handoff: "customer who needs you", payment_mismatch: "payment mismatch",
};
const n = (x: number) => x.toLocaleString("en-NG");

/** What the rep did while the owner was away: one sentence, a few honest numbers, and what was quietly held back for them. */
export function WhileAway({ shift }: { shift: ShiftReport }) {
  const tiles: [string, string, string?][] = [
    ["Customers", n(shift.conversations), `${n(shift.messages_in)} messages answered`],
    ["Paid orders", n(shift.orders_paid), shift.orders_paid ? naira(shift.revenue_kobo) : `${n(shift.payment_links)} payment link${shift.payment_links === 1 ? "" : "s"} sent`],
    ["Wrote at night", n(shift.after_hours), "between 10pm and 7am"],
    ["Voice notes & photos", n(shift.voice_notes + shift.photos), `${n(shift.voice_notes)} heard · ${n(shift.photos)} seen`],
  ];
  const held = Object.entries(shift.quiet_alerts);
  return (
    <section className="card awaycard" aria-labelledby="away-h">
      <div className="cardhead">
        <h2 id="away-h">While you were away</h2>
        <div className="filters" style={{ padding: 0 }} role="group" aria-label="Time window">
          {WINDOWS.map(([h, label]) => (
            <Link key={h} href={h === 12 ? "/" : `/?window=${h}`} className="pill" aria-current={shift.window_hours === h ? "true" : undefined} scroll={false}>{label}</Link>
          ))}
        </div>
      </div>
      <p className="awayline">{shift.headline}</p>
      <div className="awaygrid">
        {tiles.map(([label, value, hint]) => (
          <div key={label} className="awaytile">
            <div className="small muted">{label}</div>
            <div className="awayvalue">{value}</div>
            {hint && <div className="small muted">{hint}</div>}
          </div>
        ))}
      </div>
      {(held.length > 0 || shift.drafts_corrected > 0 || shift.languages.length > 0) && (
        <div className="awayfoot">
          {held.length > 0 && (
            <div className="row wrap" style={{ gap: "0.4rem" }}>
              <span className="small muted">Quietly sent to you:</span>
              {held.map(([k, c]) => <span key={k} className="badge warn">{c} {ALERT_LABEL[k] ?? k.replace(/_/g, " ")}{c === 1 ? "" : "s"}</span>)}
              {shift.waiting_on_you > 0 && <Link href="/approvals" className="small">{shift.waiting_on_you} waiting on you</Link>}
            </div>
          )}
          {shift.drafts_corrected > 0 && <p className="small muted">{n(shift.drafts_corrected)} draft{shift.drafts_corrected === 1 ? "" : "s"} fixed before sending (a price or a claim that was not yours to make).</p>}
          {shift.languages.length > 0 && (
            <div className="row wrap" style={{ gap: "0.4rem" }}>
              <span className="small muted">Spoke in:</span>
              {shift.languages.map((l) => <span key={l.name} className="badge brand">{l.name} · {n(l.turns)}</span>)}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
