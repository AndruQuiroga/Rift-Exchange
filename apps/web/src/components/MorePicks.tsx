"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { IconClose } from "./icons";

export type PickTab = { id: string; label: string; live?: boolean; body: ReactNode };

/** Everything beyond the featured calls, one tap away: a single sheet with a tab per kind of pick. */
export function MorePicks({ title, tabs, hint }: { title: string; tabs: PickTab[]; hint?: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!tabs.length) return null;
  const live = tabs.find((t) => t.live);
  return (
    <>
      <button type="button" className="morebtn" onClick={() => setOpen(live?.id ?? tabs[0].id)}>
        <span>
          <span className="t">{live ? `${live.label} open now` : "More picks"}</span>
          <span className="s">{hint ?? tabs.map((t) => t.label).join(" · ")}</span>
        </span>
        <span className="chev" aria-hidden="true">›</span>
      </button>
      {open ? <Sheet title={title} tabs={tabs} tab={open} setTab={setOpen} onClose={() => setOpen(null)} /> : null}
    </>
  );
}

function Sheet({ title, tabs, tab, setTab, onClose }: { title: string; tabs: PickTab[]; tab: string; setTab: (t: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    ref.current?.querySelector<HTMLElement>("[aria-pressed='true']")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      opener?.focus?.();
    };
  }, [onClose]);
  const current = tabs.find((t) => t.id === tab) ?? tabs[0];
  return (
    <div className="picksheet-layer">
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <div className="sheet picksheet" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="slip-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <IconClose width={20} height={20} />
          </button>
        </div>
        {tabs.length > 1 ? (
          <div className="segmented" role="group" aria-label="Kind of pick">
            {tabs.map((t) => (
              <button key={t.id} aria-pressed={t.id === current.id} onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>
        ) : null}
        <div>{current.body}</div>
        <button className="btn secondary" style={{ marginTop: 16 }} onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  );
}
