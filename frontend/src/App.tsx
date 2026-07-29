import { useEffect, useRef, useState, useCallback } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { ScrollToBottomPill } from "@/components/chat/ScrollToBottomPill";
import { useCampusChat } from "@/hooks/useCampusChat";
import { AdminDashboard } from "@/components/admin/AdminDashboard";

function ChatApp() {
  const scrollRef      = useRef<HTMLDivElement>(null);
  const endRef         = useRef<HTMLDivElement>(null);
  const [showPill, setShowPill] = useState(false);
  const [draft, setDraft]       = useState("");

  const msgRefs = useRef<Map<string, HTMLElement>>(new Map());
  const wasNearBottom = useRef(true);

  const nearBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 180;
  }, []);

  const jumpToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const scrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const scrollToMsg = useCallback((msgId: string) => {
    const el = msgRefs.current.get(msgId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  const onAnimationDone = useCallback((userMsgId: string) => {
    setTimeout(() => scrollToMsg(userMsgId), 80);
  }, [scrollToMsg]);

  const { messages, isTyping, send, submitFeedback, sessionId, newChat } = useCampusChat(onAnimationDone);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const nb = nearBottom();
      wasNearBottom.current = nb;
      if (nb) setShowPill(false);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [nearBottom]);

  useEffect(() => {
    jumpToBottom();
    wasNearBottom.current = true;
    setShowPill(false);
  }, [messages.length, isTyping, jumpToBottom]);

  const lastMsg     = messages[messages.length - 1];
  const lastContent = lastMsg?.content ?? "";
  useEffect(() => {
    if (lastMsg?.role !== "assistant") return;
    if (wasNearBottom.current) jumpToBottom();
  }, [lastContent, lastMsg?.role, jumpToBottom]);

  return (
    <div
      className="relative flex h-screen flex-col transition-colors duration-200"
      style={{ backgroundColor: "var(--background)", color: "var(--foreground)" }}
    >
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 -left-24 size-[420px] rounded-full blur-3xl"
          style={{ background: "oklch(from var(--primary) l c h / 20%)" }} />
        <div className="absolute top-1/3 -right-32 size-[380px] rounded-full blur-3xl"
          style={{ background: "oklch(from var(--accent) l c h / 25%)" }} />
        <div className="absolute -bottom-32 left-1/3 size-[360px] rounded-full blur-3xl"
          style={{ background: "oklch(from var(--secondary) l c h / 40%)" }} />
      </div>

      <ChatHeader onNewChat={newChat} />

      <div ref={scrollRef} className="relative flex-1 overflow-y-auto">
        <div className="min-h-full">
          <MessageList
            messages={messages}
            isTyping={isTyping}
            onSuggestion={(t) => setDraft(t)}
            msgRefs={msgRefs}
            sessionId={sessionId}
            onFeedbackSubmit={submitFeedback}
          />
          <div ref={endRef} />
        </div>
      </div>

      {showPill && (
        <div className="pointer-events-none fixed bottom-24 left-1/2 z-30 -translate-x-1/2">
          <ScrollToBottomPill
            onClick={() => {
              scrollToBottom();
              setShowPill(false);
              wasNearBottom.current = true;
            }}
          />
        </div>
      )}

      <ChatInput onSend={send} disabled={isTyping} value={draft} onValueChange={setDraft} />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatApp />} />
        <Route path="/admin" element={<AdminDashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
