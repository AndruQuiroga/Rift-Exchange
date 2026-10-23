"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/** good: something went your way. rival: a friend against you. money: credits coming back or time running out. */
export type ToastTone = "good" | "rival" | "money" | "info";

export type Toast = {
  id: string;
  tone: ToastTone;
  /** The square on the left: a number ("+180"), a team code or initials. */
  badge: string;
  badgeRound?: boolean;
  kicker: string;
  text: string;
  action?: { label: string; href: string };
};

const ToastContext = createContext<(t: Omit<Toast, "id"> & { key?: string }) => void>(() => {});

/** Toasts from anywhere: slide in at the top, at most two, gone after four and a half seconds or on a tap. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());
  const push = useCallback((t: Omit<Toast, "id"> & { key?: string }) => {
    if (t.key) {
      if (seen.current.has(t.key)) return; // the same news once, however many places notice it
      seen.current.add(t.key);
    }
    setToasts((prev) => [...prev, { ...t, id: `${Date.now()}-${Math.random()}` }].slice(-2));
  }, []);

  useEffect(() => {
    if (!toasts.length) return;
    const timer = setTimeout(() => setToasts((prev) => prev.slice(1)), 4500);
    return () => clearTimeout(timer);
  }, [toasts]);

  const dismiss = (id: string) => setToasts((prev) => prev.filter((x) => x.id !== id));
  return (
    <ToastContext.Provider value={push}>
      {children}
      {toasts.length ? (
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`rtoast ${t.tone}`}>
              <span className={`rt-badge${t.badgeRound ? " round" : ""}`} aria-hidden="true">{t.badge}</span>
              <span className="rt-body">
                <span className="rt-kicker">{t.kicker}</span>
                <span className="rt-text">{t.text}</span>
              </span>
              {t.action ? (
                <Link className="rt-action" href={t.action.href} onClick={() => dismiss(t.id)}>{t.action.label}</Link>
              ) : (
                <button type="button" className="rt-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>×</button>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

export const initialsOf = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
