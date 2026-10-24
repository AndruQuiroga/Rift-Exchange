"use client";

import { useEffect } from "react";
import { odds as fmtOdds, rc } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";

/** One-tap picks waiting out their undo window, then what happened to them. Lives in the app shell. */
export function QuickPicks() {
  const slip = useSlip();
  const now = useNow(250);
  const { notice, dismissNotice } = slip;
  useEffect(() => {
    if (!notice || notice.tone === "error") return;
    const t = setTimeout(dismissNotice, 6000);
    return () => clearTimeout(t);
  }, [notice, dismissNotice]);

  if (!slip.pending.length && !notice) return null;
  return (
    <div className="quickstack" role="status" aria-live="polite">
      {slip.pending.map((p) => (
        <div className="toast quick" key={p.line.outcomeId}>
          <span style={{ minWidth: 0 }}>
            <b>{p.line.outcomeLabel}</b> <span className="num">{fmtOdds(p.line.odds)}</span>
            <span className="muted num" style={{ display: "block", fontSize: 12 }}>
              Placing {rc(p.line.stake)} RC in {Math.max(1, Math.ceil((p.due - now) / 1000))} s · {p.line.eventLabel}
            </span>
          </span>
          <button type="button" className="btn secondary undo" onClick={() => slip.undo(p.line.outcomeId)}>
            Undo
          </button>
        </div>
      ))}
      {notice ? (
        <div className={`toast quick ${notice.tone}`}>
          <span>{notice.text}</span>
          {notice.tone !== "success" && slip.lines.length ? (
            <button type="button" className="link" onClick={() => { dismissNotice(); slip.setSheetOpen(true); }}>Open slip →</button>
          ) : null}
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={dismissNotice}>×</button>
        </div>
      ) : null}
    </div>
  );
}
