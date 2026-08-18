import { ArrowDown } from "lucide-react";

export function ScrollToBottomPill({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="pointer-events-auto flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium shadow-lg animate-pill-in cursor-pointer transition-all bg-background/80 backdrop-blur-md border border-border text-foreground hover:bg-muted"
    >
      <ArrowDown className="size-4" />
      New messages
    </button>
  );
}
