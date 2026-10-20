"use client";

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
  const [handle, setHandle] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/redeem", { method: "POST", json: { code, handle, display_name: name } });
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
          <li>Start with 1,000 RC, plus 1,000 RC every Worlds match day.</li>
          <li>Back match winners, scores, drafts and futures. Odds include your stake.</li>
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
            <label htmlFor="handle">Handle</label>
            <input
              id="handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value.toLowerCase())}
              required
              pattern="[a-z0-9_]{2,20}"
              autoComplete="username"
              autoCapitalize="none"
            />
            <span className="hint">2–20 lowercase letters, numbers or underscores.</span>
          </div>
          <div className="field">
            <label htmlFor="name">Display name</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} placeholder="What friends see" />
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
      </div>
    </main>
  );
}
