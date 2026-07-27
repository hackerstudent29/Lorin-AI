import { forwardRef } from "react";
import {
  GraduationCap,
  BookOpen,
  FlaskConical,
  Building2,
  Bus,
  Briefcase,
  Trophy,
  PhoneCall,
  Award,
  Coins,
} from "lucide-react";
import type { ChatMessage } from "@/types/chat";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";

type Props = {
  messages: ChatMessage[];
  isTyping: boolean;
  onSuggestion: (text: string) => void;
  msgRefs?: React.MutableRefObject<Map<string, HTMLElement>>;
  sessionId?: string;
  onFeedbackSubmit?: (messageId: string, rating: -1 | 1) => Promise<void>;
};

const SUGGESTIONS = [
  {
    icon: GraduationCap,
    label: "Admission Guide",
    hint: "Cutoffs, eligibility, steps",
    query: "What is the admission procedure, eligibility, TNEA cutoff, and fee structure for B.E / B.Tech at MSAJCE?",
  },
  {
    icon: Coins,
    label: "Tuition Fees",
    hint: "Government vs MQ fees",
    query: "What is the fee structure for B.E / B.Tech courses at MSAJCE?",
  },
  {
    icon: BookOpen,
    label: "Courses Offered",
    hint: "All 12 UG & 2 PG degrees",
    query: "List all UG and PG degree courses offered at Mohamed Sathak A.J. College of Engineering.",
  },
  {
    icon: Briefcase,
    label: "Campus Placements",
    hint: "Top packages & recruiters",
    query: "What are the placement statistics, highest package, and top recruiting companies at MSAJCE?",
  },
  {
    icon: Building2,
    label: "Boys Hostel",
    hint: "Rooms, capacity & rules",
    query: "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
  },
  {
    icon: Building2,
    label: "Girls Hostel",
    hint: "Safety & accommodation",
    query: "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
  },
  {
    icon: Bus,
    label: "Bus Routes",
    hint: "Stops, timings & routes",
    query: "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
  },
  {
    icon: FlaskConical,
    label: "Lab Facilities",
    hint: "Engineering labs & tools",
    query: "Tell me about the laboratory facilities, technology centres, and practical learning infrastructure at MSAJCE.",
  },
  {
    icon: Award,
    label: "Scholarships",
    hint: "Merit & government aid",
    query: "What scholarships are available for students at MSAJCE?",
  },
  {
    icon: Award,
    label: "About MSAJCE",
    hint: "Affiliation, NAAC grade",
    query: "Tell me about MSAJCE's affiliation, accreditation, NAAC grade, and history.",
  },
  {
    icon: Trophy,
    label: "Campus Life",
    hint: "Sports, events & clubs",
    query: "What sports facilities, athletic infrastructure, and student clubs are active at MSAJCE?",
  },
  {
    icon: PhoneCall,
    label: "Contact Info",
    hint: "Phone, email & location",
    query: "What are the official contact numbers, email addresses, and location details for visiting MSAJCE campus?",
  },
];

export const MessageList = forwardRef<HTMLDivElement, Props>(function MessageList(
  { messages, isTyping, onSuggestion, msgRefs, sessionId, onFeedbackSubmit },
  ref,
) {
  if (messages.length === 0 && !isTyping) {
    return (
      <div
        ref={ref}
        className="relative flex h-full flex-col items-center justify-center px-4 py-6 text-center sm:px-6"
      >
        {/* Hero heading */}
        <h2
          className="font-serif-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl md:text-6xl animate-fade-up"
          style={{ color: "var(--foreground)", animationDelay: "100ms" }}
        >
          Hello,{" "}
          <span
            className="animate-gradient-shift bg-clip-text text-transparent"
            style={{
              backgroundImage:
                "linear-gradient(90deg, var(--primary), var(--accent-foreground), oklch(from var(--secondary-foreground) l c h / 70%))",
            }}
          >
            future engineer
          </span>
          .
        </h2>

        {/* Subtitle */}
        <p
          className="mt-2.5 max-w-xl text-sm leading-relaxed sm:text-base animate-fade-up"
          style={{ color: "var(--muted-foreground)", animationDelay: "180ms" }}
        >
          Explore Mohamed Sathak A.J. College of Engineering (MSAJCE) — admissions, placements, courses, hostels, and campus life.
        </p>

        {/* Compact 12-card inquiry grid */}
        <div className="mt-6 grid w-full max-w-4xl grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4 sm:gap-3">
          {SUGGESTIONS.map((s, i) => {
            const Icon = s.icon;
            return (
              <button
                key={s.label}
                onClick={() => onSuggestion(s.query)}
                className="group relative flex flex-col items-start gap-1.5 overflow-hidden rounded-xl border p-3 text-left backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 animate-fade-up cursor-pointer"
                style={{
                  borderColor: "var(--border)",
                  backgroundColor: "oklch(from var(--card) l c h / 75%)",
                  animationDelay: `${260 + i * 45}ms`,
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget;
                  el.style.borderColor = "oklch(from var(--primary) l c h / 45%)";
                  el.style.backgroundColor = "var(--card)";
                  el.style.boxShadow = "0 8px 24px -12px oklch(0 0 0 / 12%)";
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget;
                  el.style.borderColor = "var(--border)";
                  el.style.backgroundColor = "oklch(from var(--card) l c h / 75%)";
                  el.style.boxShadow = "";
                }}
              >
                {/* Hover gradient overlay */}
                <span
                  className="pointer-events-none absolute inset-0 -z-10 opacity-0 transition-opacity duration-300 group-hover:opacity-100 rounded-xl"
                  style={{
                    background:
                      "linear-gradient(135deg, oklch(from var(--primary) l c h / 8%), oklch(from var(--accent) l c h / 10%))",
                  }}
                />

                {/* Icon */}
                <span
                  className="flex size-7 items-center justify-center rounded-lg transition-transform duration-300 group-hover:scale-110"
                  style={{
                    background:
                      "linear-gradient(135deg, oklch(from var(--primary) l c h / 20%), oklch(from var(--accent) l c h / 20%))",
                    color: "var(--foreground)",
                  }}
                >
                  <Icon className="size-3.5" strokeWidth={1.8} />
                </span>

                <span
                  className="text-xs font-semibold leading-snug"
                  style={{ color: "var(--foreground)" }}
                >
                  {s.label}
                </span>
                <span
                  className="text-[11px] leading-tight line-clamp-2"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {s.hint}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      aria-live="polite"
      className="mx-auto w-full max-w-5xl px-6 pb-4 pt-6"
    >
      {messages.map((m, i) => {
        const prev = messages[i - 1];
        const isGroupStart = !prev || prev.role !== m.role;
        const showTimestamp = !prev || m.createdAt - prev.createdAt > 5 * 60 * 1000;
        return (
          <div
            key={m.id}
            ref={(el) => {
              if (el) msgRefs?.current.set(m.id, el);
              else msgRefs?.current.delete(m.id);
            }}
          >
            <MessageBubble
              message={m}
              isGroupStart={isGroupStart}
              showTimestamp={showTimestamp}
              sessionId={sessionId}
              onFeedbackSubmit={onFeedbackSubmit}
              onSuggestion={onSuggestion}
            />
          </div>
        );
      })}
      {isTyping && (
        <div className="mt-6">
          <TypingIndicator />
        </div>
      )}
    </div>
  );
});
