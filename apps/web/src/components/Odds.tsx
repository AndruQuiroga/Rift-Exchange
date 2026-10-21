"use client";

import { useEffect, useRef, useState } from "react";
import { odds as fmtOdds } from "@/lib/format";

/** A live price. When it moves while you're looking, it flashes and shows ▲/▼ for a few seconds. */
export function Odds({ value }: { value: string | null }) {
  const last = useRef(value);
  const [moved, setMoved] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = last.current;
    last.current = value;
    if (!before || !value || before === value) return;
    setMoved(Number(value) > Number(before) ? "up" : "down");
    const t = setTimeout(() => setMoved(null), 4000);
    return () => clearTimeout(t);
  }, [value]);
  if (!moved) return <>{fmtOdds(value)}</>;
  return (
    <span className={`moved ${moved}`} title={`Price moved ${moved}`}>
      <span aria-hidden="true">{moved === "up" ? "▲" : "▼"}</span>
      {fmtOdds(value)}
      <span className="sr-only"> (price moved {moved})</span>
    </span>
  );
}
