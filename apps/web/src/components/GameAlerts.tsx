"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import type { EventT } from "@/lib/types";

// "Notify me when Game N opens", kept on this device. There is no push yet, so the app checks while it's open.
const KEY = "rift.gameAlerts";
type Alert = { event: string; game: number; label: string };
const listeners = new Set<() => void>();
let cache: Alert[] | null = null;

function read(): Alert[] {
  if (cache) return cache;
  try {
    cache = JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    cache = [];
  }
  return cache!;
}
function write(next: Alert[]) {
  cache = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {}
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const EMPTY: Alert[] = [];

export function useGameAlerts() {
  const alerts = useSyncExternalStore(subscribe, read, () => EMPTY);
  const has = (event: string, game: number) => alerts.some((a) => a.event === event && a.game === game);
  const toggle = useCallback((a: Alert) => {
    const now = read();
    const on = now.some((x) => x.event === a.event && x.game === a.game);
    write(on ? now.filter((x) => !(x.event === a.event && x.game === a.game)) : [...now, a]);
    if (!on && typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
  }, []);
  return { alerts, has, toggle };
}

/** The toggle on an upcoming game tab. */
export function NotifyButton({ event, game, label }: Alert) {
  const { has, toggle } = useGameAlerts();
  const on = has(event, game);
  return (
    <button type="button" className="btn small secondary" aria-pressed={on} style={{ marginTop: 12 }}
      onClick={() => toggle({ event, game, label })}>
      {on ? `We'll tell you when Game ${game} opens` : `Notify me when Game ${game} opens`}
    </button>
  );
}

/** Lives in the app shell: checks alerted games every 30 s and shows a toast when one opens. */
export function GameAlertWatcher() {
  const { alerts } = useGameAlerts();
  const [ready, setReady] = useState<Alert[]>([]);
  useEffect(() => {
    if (!alerts.length) return;
    let stop = false;
    async function check() {
      for (const a of read()) {
        try {
          const ev = await api<EventT>(`/events/${a.event}`);
          const g = ev.games?.find((x) => x.index === a.game);
          const done = !g || g.window === "NOT_NEEDED" || g.window === "DONE" || g.window === "LOCKED";
          if (stop) return;
          if (g?.window === "OPEN") {
            setReady((r) => [...r, a]);
            if (typeof Notification !== "undefined" && Notification.permission === "granted" && document.hidden) {
              new Notification(`Game ${a.game} is open`, { body: `${a.label}: winner and draft picks, for about 7 minutes.` });
            }
          }
          if (g?.window === "OPEN" || done) write(read().filter((x) => !(x.event === a.event && x.game === a.game)));
        } catch {}
      }
    }
    check();
    const t = setInterval(check, 30000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [alerts.length]);
  if (!ready.length) return null;
  const a = ready[0];
  return (
    <div className="toast" role="status">
      <span><b>Game {a.game} is open</b> · {a.label}</span>
      <Link className="link" href={`/events/${a.event}`} onClick={() => setReady((r) => r.slice(1))}>Pick now →</Link>
      <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => setReady((r) => r.slice(1))}>×</button>
    </div>
  );
}
