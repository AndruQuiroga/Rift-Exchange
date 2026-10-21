"use client";

import useSWR from "swr";
import { DeviceSignIn } from "@/components/DeviceSignIn";
import { Disclaimer } from "@/components/Disclaimer";
import { QuickToggle } from "@/components/SlipPanel";
import { api } from "@/lib/api";
import { rc } from "@/lib/format";
import { useMe, useSeason } from "@/lib/hooks";
import type { LedgerRow, Wallet } from "@/lib/types";

const KIND: Record<string, string> = {
  GRANT_OPENING: "Opening grant",
  GRANT_MATCH_DAY: "Match-day grant",
  STAKE: "Picks placed",
  PAYOUT: "Winnings",
  VOID_REFUND: "Void refund",
  REVERSAL: "Correction",
  REWARD: "Record call reward",
};

export default function ProfilePage() {
  const { data: me } = useMe();
  const { data: season } = useSeason();
  const { data: wallet } = useSWR<Wallet & { ledger: LedgerRow[] }>("/me/wallet");

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Your profile</div>
          <h1 style={{ marginTop: 6 }}>{me?.user.display_name ?? "Profile"}</h1>
        </div>
      </div>
      <div className="rows num">
        <Row label="Available" value={wallet ? `${rc(wallet.available_rc)} RC` : "—"} strong />
        <Row label="In play" value={wallet ? `${rc(wallet.open_stake_rc)} RC` : "—"} />
        <Row label="Granted so far" value={wallet ? `${rc(wallet.granted_rc)} RC` : "—"} />
        <Row
          label="Net from settled picks"
          value={wallet ? `${wallet.realized_net_rc >= 0 ? "+" : "−"}${rc(Math.abs(wallet.realized_net_rc))} RC` : "—"}
        />
        {wallet?.recovery_due_rc ? <Row label="Pending correction adjustment" value={`${rc(wallet.recovery_due_rc)} RC`} /> : null}
      </div>

      <section className="section">
        <div className="section-head">
          <h2>Picking</h2>
        </div>
        <QuickToggle />
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Your devices</h2>
        </div>
        <DeviceSignIn />
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Ledger</h2>
        </div>
        <div className="rows">
          {wallet?.ledger.map((e) => (
            <div className="row" key={e.id}>
              <div>
                <div className="title">{KIND[e.kind] ?? e.kind}</div>
                <div className="sub">
                  {e.memo ? `${e.memo} · ` : ""}
                  {new Date(e.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                </div>
              </div>
              <div className={`amount num ${e.amount_rc >= 0 ? "win" : ""}`}>
                {e.amount_rc >= 0 ? "+" : "−"}
                {rc(Math.abs(e.amount_rc))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>How the game works</h2>
        </div>
        <div className="rows">
          <div className="row" style={{ display: "block" }}>
            <p className="muted" style={{ fontSize: 14 }}>
              You start with {rc(season?.opening_grant_rc ?? 5000)} RC and get {rc(season?.match_day_grant_rc ?? 1000)} RC on every Worlds match
              day. Odds include your stake: 2.30× on 100 RC returns 230 RC, a profit of 130. Markets lock at the scheduled start, odds are fixed
              when you place, and results settle automatically once verified match data is in. Stake as much of your balance as you like.
            </p>
          </div>
        </div>
      </section>

      <button
        className="btn secondary"
        style={{ marginTop: 24 }}
        onClick={async () => {
          if (!confirm("To sign back in on this device you'll need a code from another signed-in device. Sign out?")) return;
          await api("/auth/logout", { method: "POST" });
          location.href = "/";
        }}
      >
        Sign out
      </button>
      <Disclaimer />
    </>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="row">
      <div className={strong ? "title" : "muted"}>{label}</div>
      <div className="amount" style={strong ? { fontSize: 20 } : undefined}>{value}</div>
    </div>
  );
}
