export interface Citation {
  source: string;
  page?: number | string;
  category?: string;
  url?: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export type FeedbackState = 'none' | 'thumbs_up' | 'thumbs_down' | 'submitting';

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: number;
  citations?: Citation[];
  modelUsed?: string;
  isCached?: boolean;
  tokenUsage?: TokenUsage;
  message_id?: string;
  feedbackState?: FeedbackState;
  followups?: string[];
  isAnimating?: boolean;
}

export interface EngineStatus {
  vectorStore: "connected" | "disconnected";
  database: "connected" | "disconnected";
  model: string;
}
