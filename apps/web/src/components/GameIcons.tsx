/** Small game-object icons for the scoreboard and the event timeline. Decorative: always next to text. */

type P = { size?: number; className?: string };

const DRAGON_COLORS: Record<string, string> = {
  infernal: "#ff7a45", ocean: "#3fb6e8", mountain: "#c19a5b", cloud: "#c3d2e4", hextech: "#5ee0d0",
  chemtech: "#8bd450", elder: "#c9a4ff",
};

export const dragonColor = (type: string | null | undefined) => DRAGON_COLORS[(type ?? "").toLowerCase()] ?? "#c3d2e4";

export function IconTower({ size = 14, className }: P) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M4 2h2v2h1V2h2v2h1V2h2v4l-1.5 1.5V13H13v1H3v-1h2.5V7.5L4 6z" />
    </svg>
  );
}

export function IconDragon({ size = 14, type, className }: P & { type?: string | null }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill={dragonColor(type)} aria-hidden="true">
      <path d="M8 1.5l2 3 3.5-1-1 3.5L14.5 9 11 10l-.5 4.5L8 12l-2.5 2.5L5 10 1.5 9l2-2-1-3.5 3.5 1z" />
    </svg>
  );
}

export function IconBaron({ size = 14, className }: P) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="#b48cff" aria-hidden="true">
      <path d="M8 1c3 0 5.5 2.4 5.5 5.6 0 2.2-1.2 3.6-2.5 4.4V15H5v-4C3.7 10.2 2.5 8.8 2.5 6.6 2.5 3.4 5 1 8 1zM6 6.5a1 1 0 100 2 1 1 0 000-2zm4 0a1 1 0 100 2 1 1 0 000-2z" />
    </svg>
  );
}

export function IconInhib({ size = 14, className }: P) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" />
      <circle cx="8" cy="8" r="2" fill="currentColor" />
    </svg>
  );
}

export function IconKill({ size = 14, className }: P) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <path d="M3 13l7-7M10 3h3v3M5 9l2 2M3.5 11.5l1 1" />
    </svg>
  );
}

/** The icon for a timeline event type. */
export function EventIcon({ type, detail, size = 14 }: { type: string; detail?: string | null; size?: number }) {
  if (type === "dragon") return <IconDragon size={size} type={detail} />;
  if (type === "baron") return <IconBaron size={size} />;
  if (type === "first_tower") return <IconTower size={size} />;
  if (type === "inhibitor") return <IconInhib size={size} />;
  return <IconKill size={size} />;
}
