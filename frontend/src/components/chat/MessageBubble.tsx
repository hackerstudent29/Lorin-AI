import { useState } from "react";
import { Check, Copy, BookOpen } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/chat";
import type { Components } from "react-markdown";
import { FeedbackButtons } from "@/components/chat/FeedbackButtons";

type Props = {
  message: ChatMessage;
  isGroupStart: boolean;
  showTimestamp: boolean;
  sessionId?: string;
  onFeedbackSubmit?: (messageId: string, rating: -1 | 1) => Promise<void>;
  onSuggestion?: (text: string) => void;
};

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Auto-linkify raw web URLs, emails, and phone numbers not already in markdown syntax */
function autoLinkify(text: string): string {
  // web URLs (https://, http://, or www.) not already inside markdown links
  text = text.replace(
    /(\[.*?\]\(.*?\))|((?:https?:\/\/|www\.)[a-zA-Z0-9.\-_~:/?#[\]@!$&'()*+,;=%]+)/g,
    (match, mdLink, rawUrl) => {
      if (mdLink) return mdLink;
      let clean = rawUrl;
      let trailing = "";
      while (clean.endsWith(".") || clean.endsWith(",") || clean.endsWith(";") || clean.endsWith(")")) {
        trailing = clean.slice(-1) + trailing;
        clean = clean.slice(0, -1);
      }
      const url = clean.startsWith("http") ? clean : `https://${clean}`;
      return `[${clean}](${url})${trailing}`;
    }
  );
  // emails
  text = text.replace(
    /(\[.*?\]\(.*?\))|([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})/g,
    (match, mdLink, email) => {
      if (mdLink) return mdLink;
      return `[${email}](mailto:${email})`;
    }
  );
  // phone numbers: +91-XXXXXXXXXX / 0XXXXXXXXXX / 10-digit runs
  text = text.replace(
    /(\[.*?\]\(.*?\))|(?<!\d)(\+?[\d][\d\s\-]{8,14}\d)(?!\d)/g,
    (match, mdLink, phone) => {
      if (mdLink) return mdLink;
      return `[${phone}](tel:${phone.replace(/[\s\-]/g, "")})`;
    }
  );
  return text;
}

function InteractiveLink({ href: rawHref, children }: { href?: string; children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  
  let href = (rawHref || "").trim().replace(/^\/+/, "");
  if (!href && typeof children === "string") {
    href = children.trim().replace(/^\/+/, "");
  }

  let isEmail = href.startsWith("mailto:");
  let isPhone = href.startsWith("tel:");
  let target = "_blank";

  if (!isEmail && !isPhone) {
    if (/^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(href)) {
      isEmail = true;
      href = `mailto:${href}`;
    } else {
      const digitsOnly = href.replace(/[\s\-\(\)\.]/g, "");
      if (/^(\+91|0)?\d{8,12}$/.test(digitsOnly) && !href.includes("/") && !href.includes("www") && !href.includes(".com") && !href.includes(".in")) {
        isPhone = true;
        href = `tel:${digitsOnly}`;
      } else if (!href.startsWith("http://") && !href.startsWith("https://") && !href.startsWith("#") && !href.startsWith("/api/")) {
        href = `https://${href}`;
      }
    }
  }

  if (isEmail || isPhone || href.startsWith("#") || href.startsWith("/api/")) {
    target = "_self";
  }

  const handleCopy = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    let textToCopy = href;
    if (isEmail) textToCopy = textToCopy.replace(/^mailto:/, "");
    if (isPhone) textToCopy = textToCopy.replace(/^tel:/, "");
    if (!textToCopy && typeof children === "string") textToCopy = children;
    
    navigator.clipboard.writeText(textToCopy).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <span className="relative inline group/link font-medium text-primary">
      <a
        href={href}
        target={target}
        rel="noopener noreferrer"
        className="hover:underline text-primary break-all"
      >
        {children}
      </a>
      <button
        onClick={handleCopy}
        title="Copy to clipboard"
        className="absolute left-full top-0 bottom-0 my-auto pl-1 pr-1.5 opacity-0 group-hover/link:opacity-100 transition-opacity duration-150 inline-flex items-center justify-center text-muted-foreground hover:text-foreground cursor-pointer z-20"
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-green-500 shrink-0 animate-in zoom-in-50 duration-200" />
        ) : (
          <Copy className="w-3.5 h-3.5 shrink-0" />
        )}
      </button>
    </span>
  );
}

const mdComponents: Components = {
  h1: ({ children }) => (
    <h1 className="font-serif-display text-lg font-semibold mt-3 mb-1.5" style={{ color: "var(--foreground)" }}>
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="font-serif-display text-base font-semibold mt-2.5 mb-1" style={{ color: "var(--foreground)" }}>
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-semibold mt-2 mb-0.5" style={{ color: "var(--secondary-foreground)" }}>
      {children}
    </h3>
  ),
  p: ({ children }) => <p>{children}</p>,
  ul: ({ children }) => <ul>{children}</ul>,
  ol: ({ children }) => <ol>{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  hr: () => <hr />,
  blockquote: ({ children }) => <blockquote>{children}</blockquote>,
  code: ({ children, className }) => {
    if (className?.includes("language-")) {
      return <pre><code>{children}</code></pre>;
    }
    return <code>{children}</code>;
  },
  pre: ({ children }) => <pre>{children}</pre>,
  table: ({ children }) => <div className="table-wrapper"><table>{children}</table></div>,
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr>{children}</tr>,
  th: ({ children }) => <th>{children}</th>,
  td: ({ children }) => <td>{children}</td>,
  a: ({ href, children }) => <InteractiveLink href={href}>{children}</InteractiveLink>,
  img: ({ src, alt }) => (
    <span className="my-3 block overflow-hidden rounded-xl border border-border/60 bg-secondary/40 max-w-full shadow-md transition-all hover:shadow-lg">
      <a href={src} target="_blank" rel="noopener noreferrer" className="block cursor-zoom-in">
        <img
          src={src}
          alt={alt || "MSAJCE Visual Media"}
          className="max-h-[360px] w-auto object-contain mx-auto rounded-t-xl transition-transform duration-300 hover:scale-[1.02]"
          loading="lazy"
          onError={(e) => {
            const parent = (e.target as HTMLElement).parentElement?.parentElement;
            if (parent) parent.style.display = 'none';
          }}
        />
      </a>
      {alt && (
        <span className="block p-2 text-center text-xs font-medium text-muted-foreground bg-background/80 border-t border-border/40">
          🖼️ {alt}
        </span>
      )}
    </span>
  ),
};

export function MessageBubble({ message, isGroupStart, showTimestamp, sessionId, onFeedbackSubmit, onSuggestion }: Props) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  // Detect if the message is still being animated
  const isAnimating = !!message.isAnimating;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  const processedContent = !isUser ? autoLinkify(message.content) : message.content;

  return (
    <div
      className={cn(
        "flex flex-col",
        isGroupStart ? "mt-6" : "mt-2",
        isUser ? "items-end" : "items-start"
      )}
    >
      {showTimestamp && (
        <span className="mb-1 text-[11px]" style={{ color: "var(--muted-foreground)" }}>
          {formatTime(message.createdAt)}
        </span>
      )}

      <div
        className={cn(
          "group flex w-full items-end gap-2",
          isUser ? "flex-row-reverse justify-start" : "justify-start"
        )}
      >
        <div
          className={cn(
            "relative inline-block w-fit min-w-0 max-w-[96%] sm:max-w-[82%] md:max-w-[75%] lg:max-w-[72%]",
            "flex-none break-words rounded-2xl px-4 py-3 sm:px-5 text-[14.5px] sm:text-[15px] leading-[1.6]",
            "shadow-[0_2px_10px_-4px_oklch(0_0_0_/8%)] transition-shadow hover:shadow-[0_6px_20px_-8px_oklch(0_0_0_/12%)]",
            isUser
              ? "rounded-br-md animate-msg-in-user"
              : "rounded-bl-md backdrop-blur-sm animate-msg-in-bot w-full"
          )}
          style={
            isUser
              ? {
                  background: "linear-gradient(135deg, var(--primary), oklch(from var(--primary) l c h / 85%))",
                  color: "var(--primary-foreground)",
                }
              : {
                  backgroundColor: "oklch(from var(--secondary) l c h / 90%)",
                  color: "var(--secondary-foreground)",
                }
          }
        >
          {isUser ? (
            /* User messages: plain pre-wrapped text */
            <span className="whitespace-pre-wrap">{message.content}</span>
          ) : (
            /* Bot messages: full markdown */
            <div className="bot-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {processedContent}
              </ReactMarkdown>
              {/* Blinking cursor while streaming (no tokenUsage = still animating) */}
              {isAnimating && message.content.length > 0 && !message.tokenUsage && (
                <span
                  className="animate-cursor-blink inline-block w-[2px] h-[1em] ml-0.5 align-middle rounded-sm"
                  style={{ backgroundColor: "var(--primary)" }}
                />
              )}
            </div>
          )}

          {/* ── Verified Sources ── */}
          {!isAnimating && message.citations && message.citations.length > 0 && (
            <div
              className="mt-3 pt-2 text-xs border-t animate-pill-in"
              style={{
                borderColor: "oklch(from var(--primary) l c h / 25%)",
                animationDelay: "150ms",
              }}
            >
              <div
                className="flex items-center gap-1 font-semibold mb-1"
                style={{ color: "var(--secondary-foreground)" }}
              >
                <BookOpen className="size-3" />
                <span>Verified Sources</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {message.citations.map((c, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]"
                    style={{
                      backgroundColor: "oklch(from var(--card) l c h / 70%)",
                      borderColor: "var(--border)",
                      color: "var(--muted-foreground)",
                    }}
                  >
                    📄 {c.source}
                    {c.page && <span>(p. {c.page})</span>}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* ── Suggested Follow-ups ── */}
          {!isUser && message.followups && message.followups.length > 0 && onSuggestion && !isAnimating && (
            <div
              className="mt-3 pt-2 text-xs border-t animate-pill-in"
              style={{
                borderColor: "oklch(from var(--primary) l c h / 20%)",
                animationDelay: "350ms",
              }}
            >
              <div className="text-[11px] font-semibold mb-1.5" style={{ color: "var(--muted-foreground)" }}>
                Suggested Follow-ups
              </div>
              <div className="flex flex-col gap-1.5">
                {message.followups.map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSuggestion(q)}
                    className="text-left w-full rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-muted cursor-pointer hover:translate-x-0.5"
                    style={{
                      borderColor: "var(--border)",
                      backgroundColor: "oklch(from var(--card) l c h / 40%)",
                      color: "var(--foreground)",
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── Token Usage ── */}
          {!isUser && message.tokenUsage && !isAnimating && (
            <div
              className="mt-2 pt-1.5 text-[10px] border-t flex flex-wrap items-center gap-x-2 gap-y-0.5 animate-pill-in"
              style={{
                borderColor: "oklch(from var(--primary) l c h / 20%)",
                color: "oklch(from var(--muted-foreground) l c h / 80%)",
                animationDelay: "550ms",
              }}
            >
              <span>Model: {message.modelUsed}</span>
              <span>·</span>
              {message.isCached ? (
                <span className="font-semibold" style={{ color: "oklch(0.65 0.17 145)" }}>
                  Cached ✓
                </span>
              ) : (
                <>
                  <span>Prompt: {message.tokenUsage.prompt_tokens}t</span>
                  <span>·</span>
                  <span>Completion: {message.tokenUsage.completion_tokens}t</span>
                  <span>·</span>
                  <span className="font-semibold" style={{ color: "var(--secondary-foreground)" }}>
                    Total: {message.tokenUsage.total_tokens}t
                  </span>
                </>
              )}
            </div>
          )}

          {/* ── Feedback Buttons (Req 9.4) ── */}
          {!isUser && message.tokenUsage && message.message_id && onFeedbackSubmit && !isAnimating && (
            <div className="animate-pill-in" style={{ animationDelay: "750ms" }}>
              <FeedbackButtons
                messageId={message.message_id}
                sessionId={sessionId}
                feedbackState={message.feedbackState ?? "none"}
                onFeedbackSubmit={onFeedbackSubmit}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
