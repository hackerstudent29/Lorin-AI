import { ThemeToggle } from "./ThemeToggle";
import { SquarePen } from "lucide-react";

interface ChatHeaderProps {
  onNewChat?: () => void;
}

export function ChatHeader({ onNewChat }: ChatHeaderProps) {
  return (
    <header
      className="sticky top-0 z-30 border-b px-4 py-3.5 backdrop-blur-xl sm:px-6 sm:py-4"
      style={{ borderColor: "var(--border)", backgroundColor: "oklch(from var(--background) l c h / 80%)" }}
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6">
        <div className="flex items-center gap-3">
          {/* Logo mark */}
          <div
            className="flex size-9 items-center justify-center rounded-2xl text-sm font-serif-display font-semibold shadow-sm"
            style={{
              background: "linear-gradient(135deg, var(--primary), oklch(from var(--accent) l c h))",
              color: "var(--primary-foreground)",
            }}
          >
            M
          </div>
          <div className="flex flex-col leading-tight">
            <h1 className="font-serif-display text-base font-semibold tracking-tight sm:text-lg"
              style={{ color: "var(--foreground)" }}>
              MSAJCE Assistant
            </h1>
            <span className="text-[11px] font-medium" style={{ color: "var(--muted-foreground)" }}>
              Your intelligent campus guide
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Header Online Admission Link */}
          <a
            href="https://enrollonline.co.in/Registration/Apply/MSAJCE"
            target="_blank"
            rel="noopener noreferrer"
            className="group relative flex items-center gap-2 rounded-full border px-3 py-1 text-[11.5px] font-medium tracking-wide backdrop-blur-sm transition-all duration-300 cursor-pointer"
            style={{
              borderColor: "var(--border)",
              backgroundColor: "oklch(from var(--card) l c h / 70%)",
              color: "var(--muted-foreground)",
              textDecoration: "none",
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "oklch(0.7 0.18 145 / 50%)";
              el.style.backgroundColor = "oklch(0.96 0.04 145 / 15%)";
              el.style.color = "oklch(0.4 0.18 145)";
              el.style.boxShadow = "0 0 12px oklch(0.7 0.18 145 / 25%)";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              el.style.borderColor = "var(--border)";
              el.style.backgroundColor = "oklch(from var(--card) l c h / 70%)";
              el.style.color = "var(--muted-foreground)";
              el.style.boxShadow = "none";
            }}
          >
            <span
              className="size-2 rounded-full transition-all duration-300 group-hover:scale-125 group-hover:bg-emerald-500"
              style={{ backgroundColor: "var(--muted-foreground)" }}
            />
            <span className="font-semibold text-emerald-600 dark:text-emerald-400 group-hover:inline hidden">
              MSAJCE ONLINE
            </span>
            <span className="group-hover:hidden">
              Admission Portal
            </span>
          </a>

          {onNewChat && (
            <button
              type="button"
              onClick={onNewChat}
              aria-label="Start a new chat session"
              className="flex min-h-11 min-w-11 items-center justify-center rounded-xl transition-colors focus-visible:outline-none focus-visible:ring-2 cursor-pointer"
              style={{
                color: "var(--muted-foreground)",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--muted)")}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
            >
              <SquarePen className="size-5" />
            </button>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
