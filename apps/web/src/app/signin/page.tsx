"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Brand } from "@/components/AppShell";
import { api, ApiError } from "@/lib/api";

export default function SignInPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}

function SignIn() {
  const params = useSearchParams();
  const [code, setCode] = useState(params.get("code") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const linkStarted = useRef(false);

  useEffect(() => {
    const token = new URLSearchParams(location.hash.slice(1)).get("token");
    if (!token || linkStarted.current) return;
    linkStarted.current = true;
    // Fragments never go to the server; remove the credential from this history entry too.
    history.replaceState(null, "", location.pathname);
    setBusy(true);
    api("/auth/sign-in-link", { method: "POST", json: { token } })
      .then(() => { location.replace("/"); })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Open your saved link to try again.");
        setBusy(false);
      });
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/sign-in", { method: "POST", json: { code } });
      location.href = "/";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <main className="main" style={{ paddingTop: 32 }}>
      <div className="main-inner" style={{ maxWidth: 440 }}>
        <Brand />
        <h1 className="display" style={{ fontSize: 36, textTransform: "uppercase", marginTop: 28, lineHeight: 1 }}>
          Sign in
        </h1>
        <p className="muted" style={{ marginTop: 14, fontSize: 15 }}>
          On a device where you&apos;re already signed in, open Profile and tap <strong>Sign in another device</strong>. Type the code it
          shows here.
        </p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="code">Sign-in code</label>
            <input
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              required
              autoComplete="one-time-code"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={12}
              placeholder="XXXX-XXXX"
              style={{ letterSpacing: "0.12em", fontVariantNumeric: "tabular-nums" }}
            />
            <span className="hint">Codes last 10 minutes and work once.</span>
          </div>
          {error ? (
            <div className="notice error" role="alert" style={{ marginTop: 16 }}>
              {error}
            </div>
          ) : null}
          <button className="btn" style={{ marginTop: 20 }} disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted" style={{ marginTop: 20, fontSize: 14 }}>
          No signed-in device left? Ask the league admin for a code. New here? Open the invite link you were sent, or{" "}
          <Link className="link" href="/join">
            join with an invite code
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
