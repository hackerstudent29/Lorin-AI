export function TypingIndicator() {
  return (
    <div className="flex justify-start animate-fade-up">
      <div
        className="rounded-3xl rounded-bl-md px-4 py-3"
        style={{ backgroundColor: "var(--secondary)" }}
      >
        <div className="flex items-center gap-1.5">
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="size-2 rounded-full animate-typing-dot"
              style={{
                backgroundColor: "oklch(from var(--secondary-foreground) l c h / 50%)",
                animationDelay: `${delay}ms`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
