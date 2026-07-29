import { ThemeToggle } from "./ThemeToggle";
import { SquarePen } from "lucide-react";

interface ChatHeaderProps {
  onNewChat?: () => void;
}

export function ChatHeader({ onNewChat }: ChatHeaderProps) {
  return (
    <header
      className="sticky top-0 z-30 border-b backdrop-blur-xl"
      style={{ borderColor: "var(--border)", backgroundColor: "oklch(from var(--background) l c h / 85%)" }}
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between px-3 py-2.5 sm:px-6 sm:py-3.5">

        {/* ── Left: Logo + Name ── */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="flex shrink-0 size-8 sm:size-9 items-center justify-center rounded-xl sm:rounded-2xl text-sm font-serif-display font-semibold shadow-sm"
            style={{
              background: "linear-gradient(135deg, var(--primary), oklch(from var(--accent) l c h))",
              color: "var(--primary-foreground)",
            }}
          >
            M
          </div>
          <div className="flex flex-col leading-tight min-w-0">
            <h1
              className="font-serif-display text-sm sm:text-base font-semibold tracking-tight truncate"
              style={{ color: "var(--foreground)" }}
            >
              MSAJCE Assistant
            </h1>
            <span className="text-[10px] sm:text-[11px] font-medium hidden xs:block" style={{ color: "var(--muted-foreground)" }}>
              Your intelligent campus guide
            </span>
          </div>
        </div>

        {/* ── Right: Actions ── */}
        <div className="flex items-center gap-1.5 sm:gap-2.5 shrink-0">
          {/* Admission Portal — icon-only on mobile, full pill on desktop */}
          <a
            href="https://enrollonline.co.in/Registration/Apply/MSAJCE"
            target="_blank"
            rel="noopener noreferrer"
            title="Online Admission Portal"
            className="group flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 sm:px-3 sm:py-1 transition-all duration-300 cursor-pointer"
            style={{
              borderColor: "var(--border)",
              backgroundColor: "oklch(from var(--card) l c h / 70%)",
              textDecoration: "none",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "oklch(0.7 0.18 145 / 50%)";
              el.style.backgroundColor = "oklch(0.96 0.04 145 / 15%)";
              el.style.boxShadow = "0 0 12px oklch(0.7 0.18 145 / 25%)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "var(--border)";
              el.style.backgroundColor = "oklch(from var(--card) l c h / 70%)";
              el.style.boxShadow = "none";
            }}
          >
            {/* Pulsing green dot */}
            <span className="relative flex size-2 shrink-0">
              <span
                className="absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping"
                style={{ backgroundColor: "oklch(0.7 0.18 145)" }}
              />
              <span
                className="relative inline-flex size-2 rounded-full"
                style={{ backgroundColor: "oklch(0.65 0.18 145)" }}
              />
            </span>
            {/* Text hidden on very small screens */}
            <span
              className="text-[11px] font-semibold hidden sm:inline"
              style={{ color: "oklch(0.4 0.18 145)" }}
            >
              Apply Now
            </span>
          </a>

          {/* New Chat button */}
          {onNewChat && (
            <button
              type="button"
              onClick={onNewChat}
              aria-label="Start a new chat session"
              className="flex size-8 sm:size-9 items-center justify-center rounded-xl transition-colors focus-visible:outline-none focus-visible:ring-2 cursor-pointer"
              style={{ color: "var(--muted-foreground)" }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--muted)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <SquarePen className="size-4 sm:size-5" />
            </button>
          )}

          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
