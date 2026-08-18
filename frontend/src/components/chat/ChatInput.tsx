import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
  value?: string;
  onValueChange?: (v: string) => void;
};

export function ChatInput({ onSend, disabled, value, onValueChange }: Props) {
  const [internal, setInternal] = useState("");
  const text = value ?? internal;
  const setText = onValueChange ?? setInternal;
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 144) + "px";
  }, [text]);

  const submit = () => {
    if (!text.trim() || disabled) return;
    onSend(text);
    setText("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const hasText = text.trim().length > 0;

  return (
    <div
      className="sticky bottom-0 z-20 pt-6"
      style={{
        background: "linear-gradient(to top, var(--background) 75%, transparent)",
      }}
    >
      <div className="mx-auto w-full max-w-5xl px-6 pb-4">
        <label htmlFor="chat-input" className="sr-only">Message</label>
        <div
          className="flex items-end gap-2 rounded-3xl border px-3 py-2 backdrop-blur-xl transition-all focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20"
          style={{
            borderColor: "var(--border)",
            backgroundColor: "var(--card)",
            boxShadow: "0 4px 24px -8px rgba(0, 0, 0, 0.06)",
          }}
        >
          <textarea
            id="chat-input"
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder="Ask anything about MSAJCE…"
            className="max-h-36 flex-1 resize-none bg-transparent py-2 px-2 text-[15px] leading-[1.5] placeholder:text-[#64748B] focus:outline-none"
            style={{ color: "var(--foreground)" }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!hasText || disabled}
            aria-label="Send message"
            className={cn(
              "mb-0.5 flex min-h-11 min-w-11 items-center justify-center rounded-2xl shadow-sm transition-all active:scale-95 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary bg-primary text-primary-foreground",
              hasText && !disabled && "hover:opacity-90",
              !hasText && "opacity-40 cursor-not-allowed",
            )}
          >
            <SendHorizontal className="size-5" />
          </button>
        </div>

      </div>
    </div>
  );
}
