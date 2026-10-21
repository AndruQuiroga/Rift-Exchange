"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Brand } from "@/components/AppShell";
import { api, ApiError } from "@/lib/api";

export default function JoinPage() {
  return (
    <Suspense>
      <Join />
    </Suspense>
  );
}

function Join() {
  const params = useSearchParams();
  const [code, setCode] = useState(params.get("code") ?? "");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/redeem", { method: "POST", json: { code, name } });
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
          You&apos;re invited
        </h1>
        <ul className="muted" style={{ marginTop: 14, paddingLeft: 18, display: "grid", gap: 6, fontSize: 15 }}>
          <li>Start with 5,000 RC, plus 1,000 RC every Worlds match day.</li>
          <li>Back match winners, scores and drafts. Odds include your stake.</li>
          <li>Call every team&apos;s Swiss record for free, for RC rewards.</li>
          <li>Play credits only: nothing to buy, nothing to cash out. Bragging rights only.</li>
        </ul>
        <form onSubmit={submit}>
          {!params.get("code") ? (
            <div className="field">
              <label htmlFor="code">Invite code</label>
              <input id="code" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="off" />
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="name">Your name</label>
            <input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              minLength={2}
              maxLength={32}
              autoComplete="nickname"
              placeholder="What friends see"
            />
          </div>
          {error ? (
            <div className="notice error" role="alert" style={{ marginTop: 16 }}>
              {error}
            </div>
          ) : null}
          <button className="btn" style={{ marginTop: 20 }} disabled={busy}>
            {busy ? "Joining…" : "Join the league"}
          </button>
        </form>
        <p className="muted" style={{ marginTop: 20, fontSize: 14 }}>
          Already joined on another device? Don&apos;t use a new invite, which would make a second account.{" "}
          <Link className="link" href="/signin">
            Sign in with a code
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
