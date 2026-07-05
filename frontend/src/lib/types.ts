export type MessageRole = "user" | "assistant";

export interface Source {
  title: string;
  url: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  sources?: Source[];
  streaming?: boolean;
}

export type Mode = "audience" | "creator";

export interface ClientConfig {
  client_id: string;
  status: string;
  channel_name: string;
  channel_handle: string;
  channel_url: string;
  creator_name: string;
  audience_suggestions: string[];
  creator_suggestions: string[];
}
