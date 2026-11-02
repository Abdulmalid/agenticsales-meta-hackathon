"use client";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";

type ChannelState = { bot_connected: boolean; channel: string | null; title: string | null };

/** The Telegram channel the business's bot posts to. The bot must be added to the channel as an admin who can post. */
export function TelegramChannel() {
  const toast = useToast();
  const [state, setState] = useState<ChannelState | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await call<ChannelState>("connect/telegram/channel");
    if (r.ok) setState(r.data);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save() {
    setBusy(true);
    const r = await call<ChannelState>("connect/telegram/channel", { method: "PUT", body: { channel: value.trim() } });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setValue("");
    setState(r.data);
    toast(`Posting to ${r.data.title ?? r.data.channel}.`, "ok");
  }
  async function remove() {
    setBusy(true);
    const r = await call<ChannelState>("connect/telegram/channel", { method: "DELETE" });
    setBusy(false);
    if (r.ok) setState(r.data);
  }

  if (!state || !state.bot_connected) return null;
  return (
    <div className="stack" aria-label="Telegram channel posting">
      <div className="row spread">
        <strong>Post to a Telegram channel</strong>
        {state.channel ? <Badge tone="ok">{state.title ?? state.channel}</Badge> : <Badge>No channel</Badge>}
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        Create a channel in Telegram, add your bot as an administrator with permission to post messages, then enter the channel&apos;s @username. Approved posts for &quot;Telegram channel&quot; in Content are then sent to it.
      </p>
      {state.channel ? (
        <div className="row wrap"><span className="small">Posting to <span className="mono">{state.channel}</span></span><button className="btn sm" disabled={busy} onClick={remove}>Stop</button></div>
      ) : (
        <div className="row wrap">
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="@your_channel" aria-label="Telegram channel" style={{ maxWidth: 260 }} />
          <button className="btn sm primary" disabled={busy || value.trim().length < 3} onClick={save}>{busy ? "Checking…" : "Use this channel"}</button>
        </div>
      )}
    </div>
  );
}
