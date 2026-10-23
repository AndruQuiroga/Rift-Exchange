"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { AppShell } from "@/components/AppShell";
import { SiteToasts } from "@/components/SiteToasts";
import { fetcher } from "@/lib/api";
import { SlipProvider } from "@/lib/slip";
import { ToastProvider } from "@/lib/toasts";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, revalidateOnFocus: true, dedupingInterval: 2000 }}>
      <ToastProvider>
        <SiteToasts />
        <SlipProvider>
          <AppShell>{children}</AppShell>
        </SlipProvider>
      </ToastProvider>
    </SWRConfig>
  );
}
