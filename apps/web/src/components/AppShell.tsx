"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { potentialReturn, rc, venueToday } from "@/lib/format";
import { useLiveUpdates, useMe, useSeason } from "@/lib/hooks";
import { useSlip } from "@/lib/slip";
import { IconArrow, IconExplore, IconLeague, IconPicks, IconProfile, IconToday } from "./icons";
import { GameAlertWatcher } from "./GameAlerts";
import { QuickPicks } from "./QuickPicks";
import { SlipPanel } from "./SlipPanel";

const NAV = [
  { href: "/", label: "Today", Icon: IconToday },
  { href: "/explore", label: "Explore", Icon: IconExplore },
  { href: "/picks", label: "My Picks", short: "Picks", Icon: IconPicks },
  { href: "/league", label: "League", Icon: IconLeague },
  { href: "/profile", label: "Profile", short: "You", Icon: IconProfile },
];

function active(pathname: string, href: string) {
  return href === "/" ? pathname === "/" || pathname.startsWith("/events") : pathname.startsWith(href);
}

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Rift Exchange home">
      <span className="brand-mark" aria-hidden="true">R</span>
      <span>
        <span className="brand-name">Rift Exchange</span>
        <span className="brand-sub" style={{ display: "block" }}>Worlds 2026</span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { data: me, error } = useMe();
  const slip = useSlip();
  const { data: season } = useSeason();
  const grantToday = season ? season.match_days.includes(venueToday(season.timezone)) : false;
  useLiveUpdates(Boolean(me));

  if (pathname.startsWith("/join") || pathname.startsWith("/signin")) return <>{children}</>;
  if (error instanceof ApiError && error.status === 401) return <SignedOut />;

  return (
    <div className="shell">
      <GameAlertWatcher />
      <QuickPicks />
      <aside className="siderail">
        <Brand />
        <nav aria-label="Main">
          {NAV.map(({ href, label, Icon }) => (
            <Link key={href} href={href} aria-current={active(pathname, href) ? "page" : undefined}>
              <Icon /> {label}
            </Link>
          ))}
        </nav>
        <div className="foot">
          Private league · play credits only.
          <br />
          Not endorsed by Riot Games.
        </div>
      </aside>

      <main className="main">
        <div className="main-inner">
          <header className="topbar">
            <Brand />
            <span className="sr-only">Rift Exchange</span>
            <Link href="/profile" className="topbar-balance num" aria-label="Wallet">
              <b>{me ? `${rc(me.wallet.available_rc)} RC` : "—"}</b>
              {me && (me.wallet.today_net_rc ?? 0) !== 0 ? (
                <span className={(me.wallet.today_net_rc ?? 0) > 0 ? "grant" : "loss"}>
                  {(me.wallet.today_net_rc ?? 0) > 0 ? "+" : "−"}{rc(Math.abs(me.wallet.today_net_rc ?? 0))} today
                </span>
              ) : <span>{grantToday ? "± 0 today" : "Available"}</span>}
            </Link>
          </header>
          {children}
        </div>
      </main>

      <aside className="sliprail" aria-label="Slip">
        <SlipPanel />
      </aside>

      {slip.lines.length > 0 && !slip.sheetOpen ? (
        <button className="slipbar" onClick={() => slip.setSheetOpen(true)}>
          <span>
            <span className="n num">{slip.lines.length}</span>
            <span className="num">
              {rc(slip.lines.reduce((s, l) => s + (l.stake ?? 0), 0))} RC
              <span className="ret"> → {rc(slip.lines.reduce((s, l) => s + (l.stake ? potentialReturn(l.stake, l.odds) : 0), 0))} RC</span>
            </span>
          </span>
          <span>
            Review <IconArrow width={16} height={16} style={{ verticalAlign: "-3px" }} />
          </span>
        </button>
      ) : null}
      {slip.sheetOpen ? <SlipSheet setOpen={slip.setSheetOpen} /> : null}

      <nav className="bottomnav" aria-label="Main">
        {NAV.map(({ href, label, short, Icon }) => (
          <Link key={href} href={href} aria-current={active(pathname, href) ? "page" : undefined}>
            <Icon />
            {short ?? label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

function SlipSheet({ setOpen }: { setOpen: (open: boolean) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const firstPath = useRef(pathname);
  useEffect(() => {
    if (pathname !== firstPath.current) setOpen(false); // navigated from inside the sheet
  }, [pathname, setOpen]);
  useEffect(() => {
    const onClose = () => setOpen(false);
    const opener = document.activeElement as HTMLElement | null;
    // Browser back closes the sheet without losing picks. The history entry is pushed a tick later so
    // an immediate unmount (React StrictMode runs effects twice in dev) cancels it instead of queueing
    // a back() that would close the remounted sheet.
    let pushed = false;
    const onPop = () => onClose();
    const timer = window.setTimeout(() => {
      history.pushState({ riftSheet: true }, "");
      pushed = true;
      window.addEventListener("popstate", onPop);
    }, 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") history.back();
      if (e.key === "Tab" && ref.current) {
        const focusable = ref.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), a[href]");
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    ref.current?.querySelector<HTMLElement>("input, button")?.focus();
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("popstate", onPop);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      if (pushed && history.state?.riftSheet) history.back();
      opener?.focus?.();
    };
  }, [setOpen]);
  return (
    <div className="sheet-layer">
      <div className="scrim" onClick={() => history.back()} aria-hidden="true" />
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Your slip" ref={ref}>
        <div className="grabber" aria-hidden="true" />
        <SlipPanel onClose={() => history.back()} />
      </div>
    </div>
  );
}

function SignedOut() {
  return (
    <main className="main" style={{ paddingTop: 40 }}>
      <div className="main-inner" style={{ maxWidth: 440 }}>
        <Brand />
        <h1 className="display" style={{ fontSize: 34, textTransform: "uppercase", marginTop: 28, lineHeight: 1 }}>
          Invite only
        </h1>
        <p className="muted" style={{ marginTop: 10 }}>
          Rift Exchange is a private prediction league for friends watching Worlds 2026. Open the invite link you were sent to join.
        </p>
        <Link className="btn secondary" href="/signin" style={{ marginTop: 24 }}>
          I already have an account
        </Link>
      </div>
    </main>
  );
}
