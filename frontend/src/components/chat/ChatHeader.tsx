import { ThemeToggle } from "./ThemeToggle";
import { SquarePen } from "lucide-react";
import { MSAJLogo } from "../ui/MSAJLogo";

interface ChatHeaderProps {
  onNewChat?: () => void;
}

export function ChatHeader({ onNewChat }: ChatHeaderProps) {
  return (
    <header
      className="sticky top-0 z-30 border-b backdrop-blur-xl"
      style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }}
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between px-3 py-2.5 sm:px-6 sm:py-3.5">

        {/* ── Left: Logo + Name ── */}
        <div className="flex items-center gap-2.5 min-w-0">
          <MSAJLogo size={34} glow variant="theme" className="shrink-0 transition-transform duration-300 hover:scale-105" />
          <div className="flex flex-col leading-tight min-w-0">
            <div className="flex items-center gap-1.5">
              <h1
                className="font-black uppercase tracking-tighter text-sm sm:text-base leading-[0.95] truncate"
                style={{ color: "var(--foreground)" }}
              >
                MSAJCE Assistant
              </h1>
              <span className="shrink-0 rounded-full px-2 py-0.5 text-[9px] font-black tracking-[0.2em] uppercase border bg-secondary text-secondary-foreground border-border shadow-2xs">
                Code: 1301
              </span>
            </div>
            <span className="text-[10px] sm:text-[11px] font-medium hidden xs:block tracking-wide uppercase mt-0.5" style={{ color: "var(--muted-foreground)" }}>
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
              backgroundColor: "var(--card)",
              textDecoration: "none",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "var(--primary)";
              el.style.backgroundColor = "var(--secondary)";
              el.style.boxShadow = "0 0 12px rgba(0, 93, 166, 0.25)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "var(--border)";
              el.style.backgroundColor = "var(--card)";
              el.style.boxShadow = "none";
            }}
          >
            {/* Pulsing blue dot */}
            <span className="relative flex size-2 shrink-0">
              <span
                className="absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping bg-primary"
              />
              <span
                className="relative inline-flex size-2 rounded-full bg-primary"
              />
            </span>
            {/* Text hidden on very small screens */}
            <span
              className="text-[11px] font-black uppercase tracking-[0.2em] hidden sm:inline"
              style={{ color: "var(--primary)" }}
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
