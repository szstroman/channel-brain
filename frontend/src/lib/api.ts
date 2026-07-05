import type { Source, Mode, ClientConfig } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface StreamEvent {
  type: "sources" | "token" | "done" | "error";
  text?: string;
  sources?: Source[];
  message?: string;
}

export interface StreamRequest {
  question: string;
  client_id: string;
  mode: Mode;
  history: { role: "user" | "assistant"; content: string }[];
}

/**
 * POSTs to the streaming endpoint and yields parsed SSE events.
 */
export async function* streamQuery(
  req: StreamRequest,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_URL}/api/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Backend returned no body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const dataLine = frame
          .split("\n")
          .find((line) => line.startsWith("data:"));
        if (dataLine) {
          const payload = dataLine.slice(5).trim();
          if (payload) {
            try {
              const parsed = JSON.parse(payload) as StreamEvent;
              yield parsed;
            } catch {
              // Malformed frame — skip
            }
          }
        }

        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Fetch client display config + suggestion lists.
 */
export async function fetchClient(clientId: string): Promise<ClientConfig> {
  const response = await fetch(`${API_URL}/api/client/${encodeURIComponent(clientId)}`);
  if (!response.ok) {
    throw new Error(`Client fetch failed: ${response.status}`);
  }
  return response.json();
}

export interface PreloadedResponse {
  answer: string;
  sources: Source[];
}

/**
 * Look up a preloaded answer. Returns null on cache miss.
 * Never throws for expected misses — only for actual network errors.
 */
export async function fetchPreloaded(
  clientId: string,
  mode: Mode,
  question: string
): Promise<PreloadedResponse | null> {
  try {
    const response = await fetch(`${API_URL}/api/preloaded`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, mode, question }),
    });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}

export interface LeadRequest {
  email: string;
  channel_url: string;
  client_id: string;
  consent: boolean;
}

/**
 * Submit a lead capture form. Throws on failure so the form can surface
 * a real error to the user.
 */
export async function submitLead(req: LeadRequest): Promise<void> {
  const response = await fetch(`${API_URL}/api/lead`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    let msg = `Server returned ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) msg = body.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
}
