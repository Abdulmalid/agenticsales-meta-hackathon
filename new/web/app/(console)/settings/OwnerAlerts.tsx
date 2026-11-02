"use client";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";

type AlertsState = { bot: string | null; bot_ready: boolean; linked: boolean; code: string };

/** Silent alerts: when your rep needs the owner it never tells the customer; it messages the owner on Telegram instead. */
export function OwnerAlerts() {
  const toast = useToast();
  const [state, setState] = useState<AlertsState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await call<AlertsState>("alerts");
    if (r.ok) setState(r.data);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function test() {
    setBusy(true);
    const r = await call("alerts/test", { method: "POST", body: {} });
    setBusy(false);
    toast(r.ok ? "Test alert sent. Check Telegram." : r.error, r.ok ? "ok" : "error");
  }

  async function turnOff() {
    setBusy(true);
    const r = await call("alerts", { method: "DELETE" });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    toast("Alerts turned off.", "ok");
    load();
  }

  if (!state || !state.bot_ready) return null;
  return (
    <div className="stack" aria-label="Owner alerts">
      <div className="row spread">
        <strong>Alerts to you</strong>
        {state.linked ? <Badge tone="ok">On</Badge> : <Badge>Not linked</Badge>}
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        When a customer needs you (a discount to approve, a payment that doesn&apos;t match, an upset customer) your rep keeps chatting normally and quietly sends you a message here instead of telling the customer anything.
      </p>
      {state.linked ? (
        <div className="row wrap">
          <button className="btn sm" disabled={busy} onClick={test}>Send a test alert</button>
          <button className="btn sm" disabled={busy} onClick={turnOff}>Turn off</button>
        </div>
      ) : (
        <p className="small" style={{ margin: 0 }}>
          To turn them on, open {state.bot ?? "your bot"} in Telegram and send <span className="mono">/owner {state.code}</span>
        </p>
      )}
    </div>
  );
}
