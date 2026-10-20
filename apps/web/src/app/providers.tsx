"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { AppShell } from "@/components/AppShell";
import { fetcher } from "@/lib/api";
import { SlipProvider } from "@/lib/slip";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, revalidateOnFocus: true, dedupingInterval: 2000 }}>
      <SlipProvider>
        <AppShell>{children}</AppShell>
      </SlipProvider>
    </SWRConfig>
  );
}
