"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Code = { code: string; expires_at: string };

/** Makes a one-time code that signs another phone or computer into this account. */
export function DeviceSignIn() {
  const [code, setCode] = useState<Code | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!code) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [code]);

  async function create() {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      setCode(await api<Code>("/auth/sign-in-codes", { method: "POST" }));
      setNow(Date.now());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const left = code ? Math.max(0, Math.floor((Date.parse(code.expires_at) - now) / 1000)) : 0;
  const link = code && typeof location !== "undefined" ? `${location.origin}/signin?code=${code.code}` : "";

  return (
    <div className="rows">
      <div className="row" style={{ display: "block" }}>
        {code && left > 0 ? (
          <>
            <p className="muted" style={{ fontSize: 14 }}>
              On the other device, go to <strong>{typeof location !== "undefined" ? location.host : "this site"}/signin</strong> and enter:
            </p>
            <div className="display num" style={{ fontSize: 34, letterSpacing: "0.12em", margin: "10px 0 4px" }} aria-live="polite">
              {code.code}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              Works once · expires in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
            </div>
            <button
              className="btn secondary small"
              style={{ marginTop: 12 }}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(link);
                  setCopied(true);
                } catch {
                  setError("Couldn't copy. Type the code instead.");
                }
              }}
            >
              {copied ? "Link copied" : "Copy sign-in link"}
            </button>
          </>
        ) : (
          <>
            <p className="muted" style={{ fontSize: 14 }}>
              Use your account on a phone and a computer. Make a code here, then type it on the other device. Nobody else should see it.
            </p>
            {code ? (
              <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                That code expired.
              </p>
            ) : null}
            <button className="btn secondary small" style={{ marginTop: 12 }} disabled={busy} onClick={create}>
              {busy ? "Making a code…" : code ? "Make a new code" : "Sign in another device"}
            </button>
          </>
        )}
        {error ? (
          <div className="notice error" role="alert" style={{ marginTop: 12 }}>
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
