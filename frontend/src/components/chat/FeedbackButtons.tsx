import { ThumbsUp, ThumbsDown, Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FeedbackState } from "@/types/chat";

interface FeedbackButtonsProps {
  messageId: string;
  sessionId?: string;
  feedbackState: FeedbackState;
  onFeedbackSubmit: (messageId: string, rating: -1 | 1) => Promise<void>;
}

export function FeedbackButtons({
  messageId,
  sessionId,
  feedbackState,
  onFeedbackSubmit,
}: FeedbackButtonsProps) {
  const isDisabled = feedbackState !== "none";
  const isSubmitting = feedbackState === "submitting";

  const handleClick = (rating: -1 | 1) => {
    if (isDisabled) return;
    onFeedbackSubmit(messageId, rating);
  };

  return (
    <div
      className="flex items-center gap-1.5 mt-2 pt-2 border-t"
      style={{ borderColor: "oklch(from var(--primary) l c h / 15%)" }}
    >
      <span
        className="text-[10px] mr-0.5"
        style={{ color: "var(--muted-foreground)" }}
      >
        Helpful?
      </span>

      {/* Thumbs Up */}
      <button
        onClick={() => handleClick(1)}
        disabled={isDisabled}
        aria-label="Thumbs up — helpful"
        title="This answer was helpful"
        className={cn(
          "inline-flex items-center justify-center w-6 h-6 rounded-full",
          "border transition-all duration-150",
          "disabled:cursor-default",
          feedbackState === "thumbs_up"
            ? "border-transparent text-white"
            : feedbackState === "none"
            ? "border-transparent hover:border-current cursor-pointer opacity-50 hover:opacity-100"
            : "border-transparent opacity-30"
        )}
        style={
          feedbackState === "thumbs_up"
            ? { background: "var(--primary)", color: "var(--primary-foreground)" }
            : { color: "var(--muted-foreground)" }
        }
        onMouseEnter={(e) => {
          if (feedbackState === "none") e.currentTarget.style.color = "oklch(0.65 0.17 145)";
        }}
        onMouseLeave={(e) => {
          if (feedbackState === "none") e.currentTarget.style.color = "var(--muted-foreground)";
        }}
      >
        {feedbackState === "thumbs_up" ? (
          <Check className="size-3" />
        ) : isSubmitting ? (
          <Loader2 className="size-3 animate-spin" />
        ) : (
          <ThumbsUp className="size-3" />
        )}
      </button>

      {/* Thumbs Down */}
      <button
        onClick={() => handleClick(-1)}
        disabled={isDisabled}
        aria-label="Thumbs down — not helpful"
        title="This answer was not helpful"
        className={cn(
          "inline-flex items-center justify-center w-6 h-6 rounded-full",
          "border transition-all duration-150",
          "disabled:cursor-default",
          feedbackState === "thumbs_down"
            ? "border-transparent text-white"
            : feedbackState === "none"
            ? "border-transparent hover:border-current cursor-pointer opacity-50 hover:opacity-100"
            : "border-transparent opacity-30"
        )}
        style={
          feedbackState === "thumbs_down"
            ? { background: "oklch(0.55 0.2 25)", color: "white" }
            : { color: "var(--muted-foreground)" }
        }
        onMouseEnter={(e) => {
          if (feedbackState === "none") e.currentTarget.style.color = "oklch(0.55 0.2 25)";
        }}
        onMouseLeave={(e) => {
          if (feedbackState === "none") e.currentTarget.style.color = "var(--muted-foreground)";
        }}
      >
        {feedbackState === "thumbs_down" ? (
          <Check className="size-3" />
        ) : (
          <ThumbsDown className="size-3" />
        )}
      </button>
    </div>
  );
}
