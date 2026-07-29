import { useState, useCallback, useRef, useEffect } from "react";
import type { ChatMessage } from "@/types/chat";

const CHARS_PER_TICK = 18;
const TICK_MS = 12;

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

export function useCampusChat(onAnimationDone?: (userMsgId: string) => void) {
  const [messages, setMessages]   = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping]   = useState(false);
  const animatingRef              = useRef<Set<string>>(new Set());
  const [sessionId, setSessionId] = useState<string>(() => {
    const saved = localStorage.getItem("msajce_chat_session_id");
    if (saved) return saved;
    const newId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
    localStorage.setItem("msajce_chat_session_id", newId);
    return newId;
  });

  useEffect(() => {
    let active = true;
    async function loadHistory() {
      try {
        const res = await fetch(`${API_BASE}/api/chat/history/${sessionId}`);
        if (res.ok && active) {
          const data = await res.json();
          // Only the last message keeps its followups — strip all others
          const cleaned = (data as ChatMessage[]).map((m, i, arr) =>
            i < arr.length - 1 ? { ...m, followups: [] } : m
          );
          if (active) setMessages(cleaned);
        }
      } catch (err) {
        console.error("Failed to load chat history:", err);
      }
    }
    loadHistory();
    return () => {
      active = false;
    };
  }, [sessionId]);

  const newChat = useCallback(() => {
    const newId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
    localStorage.setItem("msajce_chat_session_id", newId);
    setSessionId(newId);
    setMessages([]);
  }, []);

  const animateMessage = useCallback(
    (msgId: string, fullText: string, userMsgId: string) => {
      animatingRef.current.add(msgId);
      let revealed = 0;

      const tick = () => {
        if (!animatingRef.current.has(msgId)) return;
        revealed = Math.min(revealed + CHARS_PER_TICK, fullText.length);
        
        // Ensure we reveal at natural word boundaries for silky smooth text streaming
        if (revealed < fullText.length) {
          const nextSpace = fullText.indexOf(" ", revealed);
          if (nextSpace !== -1 && nextSpace - revealed < 12) {
            revealed = nextSpace + 1;
          }
        }

        const done = revealed >= fullText.length;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId
              ? { ...m, content: fullText.slice(0, revealed), isAnimating: !done }
              : m
          )
        );
        if (!done) {
          setTimeout(tick, TICK_MS);
        } else {
          animatingRef.current.delete(msgId);
          onAnimationDone?.(userMsgId);
        }
      };

      setTimeout(tick, TICK_MS);
    },
    [onAnimationDone]
  );

  const send = useCallback(
    async (text: string) => {
      if (!text.trim()) return;

      const userMsgId = "msg_" + Date.now();
      const userMessage: ChatMessage = {
        id: userMsgId,
        role: "user",
        content: text.trim(),
        createdAt: Date.now(),
      };

      setMessages((prev) => [
        ...prev.map((m) => ({ ...m, followups: [] })),
        userMessage
      ]);
      setIsTyping(true);

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: sessionId }),
        });

        if (res.ok) {
          const data     = await res.json();
          const aiMsgId  = "msg_" + (Date.now() + 1);
          const fullText = data.answer ?? "";

          const aiMessage: ChatMessage = {
            id: aiMsgId,
            role: "assistant",
            content: "",
            createdAt: Date.now(),
            citations:     data.citations  || [],
            modelUsed:     data.modelUsed  || "meta/llama-3.1-8b-instruct",
            isCached:      data.isCached   || false,
            tokenUsage:    data.tokenUsage,
            message_id:    data.message_id || undefined,
            feedbackState: "none" as const,
            followups:     data.followups  || [],
            isAnimating:   true,
          };

          setMessages((prev) => [
            ...prev.map((m) => ({ ...m, followups: [] })),
            aiMessage
          ]);
          setIsTyping(false);
          animateMessage(aiMsgId, fullText, userMsgId);
        } else {
          const errText = await res.text();
          console.error("API error:", res.status, errText);
          setMessages((prev) => [
            ...prev,
            {
              id: "msg_" + (Date.now() + 1),
              role: "assistant",
              content: "I could not retrieve an answer at this moment. Please verify backend connection.",
              createdAt: Date.now(),
            },
          ]);
          setIsTyping(false);
        }
      } catch (err) {
        console.error("Chat network error:", err);
        setMessages((prev) => [
          ...prev,
          {
            id: "msg_" + (Date.now() + 1),
            role: "assistant",
            content: "Network error connecting to live MSAJCE RAG API server.",
            createdAt: Date.now(),
          },
        ]);
        setIsTyping(false);
      }
    },
    [animateMessage, sessionId]
  );

  const submitFeedback = useCallback(
    async (messageId: string, rating: -1 | 1): Promise<void> => {
      // Optimistic update to 'submitting'
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === messageId ? { ...m, feedbackState: "submitting" as const } : m
        )
      );
      try {
        const res = await fetch(`${API_BASE}/api/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message_id: messageId,
            session_id: sessionId,
            rating,
          }),
        });
        if (!res.ok) throw new Error(`Feedback HTTP ${res.status}`);
        const finalState: "thumbs_up" | "thumbs_down" = rating === 1 ? "thumbs_up" : "thumbs_down";
        setMessages((prev) =>
          prev.map((m) =>
            m.message_id === messageId ? { ...m, feedbackState: finalState } : m
          )
        );
      } catch (err) {
        console.error("[Feedback] Submission failed:", err);
        // Revert to 'none'
        setMessages((prev) =>
          prev.map((m) =>
            m.message_id === messageId ? { ...m, feedbackState: "none" as const } : m
          )
        );
      }
    },
    [sessionId]
  );

  return { messages, isTyping, send, submitFeedback, sessionId, newChat };
}
