import { useState, useCallback, useRef, useEffect } from "react";
import type { ChatMessage } from "@/types/chat";

const CHARS_PER_TICK = 18;
const TICK_MS = 12;

const API_BASE = import.meta.env.VITE_API_URL || "";

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
          setMessages(data);
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

      setMessages((prev) => [...prev, userMessage]);
      setIsTyping(true);

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: sessionId, stream: true }),
        });

        if (res.ok) {
          setIsTyping(false);
          const aiMsgId  = "msg_" + (Date.now() + 1);
          
          setMessages((prev) => [
            ...prev,
            {
              id: aiMsgId,
              role: "assistant",
              content: "",
              createdAt: Date.now(),
              citations: [],
              modelUsed: "meta/llama-3.1-8b-instruct",
              isCached: false,
              feedbackState: "none" as const,
              followups: [],
              isAnimating: true,
            }
          ]);

          const contentType = res.headers.get("content-type") || "";
          if (contentType.includes("application/json")) {
            const data = await res.json();
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? {
                  ...m,
                  content: data.answer,
                  citations: data.citations || [],
                  followups: data.followups || [],
                  message_id: data.message_id,
                  tokenUsage: data.tokenUsage,
                  isCached: data.isCached || false,
                  modelUsed: data.modelUsed || "meta/llama-3.1-8b-instruct",
                  isAnimating: false,
                } : m
              )
            );
            onAnimationDone?.(userMsgId);
            return;
          }

          if (!res.body) throw new Error("No response body");
          const reader = res.body.getReader();
          const decoder = new TextDecoder("utf-8");
          let done = false;
          let buffer = "";

          while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
              buffer += decoder.decode(value, { stream: true });
              let boundary = buffer.indexOf("\\n\\n");
              while (boundary !== -1) {
                const message = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                
                if (message.startsWith("data: ")) {
                  try {
                    const data = JSON.parse(message.slice(6));
                    if (data.type === "content") {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === aiMsgId ? { ...m, content: m.content + data.text } : m
                        )
                      );
                    } else if (data.type === "metadata") {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === aiMsgId ? {
                            ...m,
                            citations: data.citations || [],
                            followups: data.followups || [],
                            message_id: data.message_id,
                            tokenUsage: data.tokenUsage,
                            isAnimating: false,
                          } : m
                        )
                      );
                    } else if (data.type === "error") {
                      console.error("Stream error:", data.text);
                      setMessages((prev) => prev.map((m) => m.id === aiMsgId ? { ...m, isAnimating: false } : m));
                    }
                  } catch(e) {
                     // ignore partial JSON parse errors
                  }
                }
                boundary = buffer.indexOf("\\n\\n");
              }
            }
          }
          
          onAnimationDone?.(userMsgId);

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
    [sessionId, onAnimationDone]
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
