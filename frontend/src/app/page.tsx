"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { flushSync } from "react-dom";
import { streamQuery, fetchClient, fetchPreloaded } from "@/lib/api";
import type { Message, Source, Mode, ClientConfig } from "@/lib/types";
import { ChatMessage } from "@/components/ChatMessage";
import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import { ChatInput } from "@/components/ChatInput";
import { Sidebar } from "@/components/Sidebar";
import { Suggestions } from "@/components/Suggestions";
import { ModeToggle } from "@/components/ModeToggle";
import { LeadForm } from "@/components/LeadForm";

const MIN_THINKING_MS = 4000;
const CLIENT_ID = "koerner-office";
const MAX_TURNS = 8; // Each turn = 1 user + 1 assistant. So 8 user messages max.
const WARN_TURNS_REMAINING = 2;

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function countUserTurns(messages: Message[]): number {
  return messages.filter((m) => m.role === "user").length;
}

export default function Home() {
  const [mode, setMode] = useState<Mode>("audience");
  const [client, setClient] = useState<ClientConfig | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [thinking, setThinking] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Set the mode-aware accent CSS variable at the root so all Tailwind
  // var(--accent) utilities resolve to the correct color per mode.
  useEffect(() => {
    const root = document.documentElement;
    if (mode === "creator") {
      root.style.setProperty("--accent", "#d4a359");
      root.style.setProperty("--accent-hover", "#c4934a");
      root.style.setProperty("--accent-glow", "rgba(212,163,89,0.1)");
      root.style.setProperty("--accent-glow-soft", "rgba(212,163,89,0.06)");
    } else {
      root.style.setProperty("--accent", "#5eb8ff");
      root.style.setProperty("--accent-hover", "#3a9aec");
      root.style.setProperty("--accent-glow", "rgba(94,184,255,0.1)");
      root.style.setProperty("--accent-glow-soft", "rgba(94,184,255,0.06)");
    }
  }, [mode]);

  // Fetch client config on mount
  useEffect(() => {
    fetchClient(CLIENT_ID)
      .then(setClient)
      .catch((e) => {
        setClientError(e instanceof Error ? e.message : "Failed to load client");
      });
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, thinking]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setThinking(false);
    setStreaming(false);
  }, []);

  const handleModeChange = useCallback(
    (newMode: Mode) => {
      abortRef.current?.abort();
      setMode(newMode);
      setMessages([]);
      setThinking(false);
      setStreaming(false);
    },
    []
  );

  const turnCount = countUserTurns(messages);
  const atLimit = turnCount >= MAX_TURNS;
  const remaining = MAX_TURNS - turnCount;

  // Deliver a preloaded (cached) answer with simulated token streaming so the
  // UX matches a live query exactly. We already have the full answer — we just
  // chunk it out at a rate that feels natural.
  const deliverPreloaded = useCallback(
    async (question: string, answer: string, sources: Source[]) => {
      const userMsg: Message = { id: makeId(), role: "user", content: question };
      const assistantId = makeId();
      setMessages((prev) => [...prev, userMsg]);
      setThinking(true);
      setStreaming(true);

      // Same 1.2s minimum thinking window as live queries
      await new Promise((r) => setTimeout(r, MIN_THINKING_MS));

      // Render the empty assistant shell + sources chips immediately
      flushSync(() => {
        setThinking(false);
        setMessages((prev) => [
          ...prev,
          {
            id: assistantId,
            role: "assistant",
            content: "",
            sources,
            streaming: true,
          },
        ]);
      });

      // Stream tokens client-side at ~90 characters/sec.
      const answerLen = answer.length;
      const charsPerSecond = 90;
      const chunkSize = 4;
      const delayPerChunk = Math.max(
        10,
        Math.floor((chunkSize / charsPerSecond) * 1000)
      );

      let buffered = "";
      for (let i = 0; i < answerLen; i += chunkSize) {
        buffered = answer.slice(0, i + chunkSize);
        flushSync(() => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: buffered } : m
            )
          );
        });
        await new Promise((r) => setTimeout(r, delayPerChunk));
      }

      // Mark streaming complete
      flushSync(() => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: answer, streaming: false }
              : m
          )
        );
      });
      setStreaming(false);
    },
    []
  );

  // Live query via the streaming endpoint.
  const runLiveQuery = useCallback(
    async (question: string) => {
      const userMsg: Message = { id: makeId(), role: "user", content: question };
      const assistantId = makeId();

      // Build history from current messages BEFORE we append the new user msg.
      // Backend expects prior turns only.
      const history = messages.map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));

      setMessages((prev) => [...prev, userMsg]);
      setThinking(true);
      setStreaming(true);
      const thinkingStartedAt = Date.now();

      abortRef.current = new AbortController();

      let messageRendered = false;
      let bufferedText = "";
      let bufferedSources: Source[] = [];

      const renderAssistantMessage = () => {
        flushSync(() => {
          setThinking(false);
          setMessages((prev) => [
            ...prev,
            {
              id: assistantId,
              role: "assistant",
              content: bufferedText,
              sources: bufferedSources,
              streaming: true,
            },
          ]);
        });
        messageRendered = true;
      };

      const appendToMessage = (chunk: string) => {
        bufferedText += chunk;
        flushSync(() => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: bufferedText } : m
            )
          );
        });
      };

      try {
        const stream = streamQuery(
          {
            question,
            client_id: CLIENT_ID,
            mode,
            history,
          },
          abortRef.current.signal
        );

        for await (const event of stream) {
          if (event.type === "sources" && event.sources) {
            bufferedSources = event.sources;
            if (messageRendered) {
              flushSync(() => {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, sources: bufferedSources } : m
                  )
                );
              });
            }
          } else if (event.type === "token" && event.text) {
            if (!messageRendered) {
              const elapsed = Date.now() - thinkingStartedAt;
              const remainingMs = MIN_THINKING_MS - elapsed;
              if (remainingMs > 0) {
                await new Promise((r) => setTimeout(r, remainingMs));
              }
              bufferedText = event.text;
              renderAssistantMessage();
            } else {
              appendToMessage(event.text);
            }
          } else if (event.type === "done") {
            if (!messageRendered) {
              flushSync(() => {
                setThinking(false);
                setMessages((prev) => [
                  ...prev,
                  {
                    id: assistantId,
                    role: "assistant",
                    content: bufferedText || "(No response)",
                    sources: event.sources ?? bufferedSources,
                  },
                ]);
              });
            } else {
              flushSync(() => {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? {
                          ...m,
                          streaming: false,
                          sources: event.sources ?? m.sources,
                        }
                      : m
                  )
                );
              });
            }
          } else if (event.type === "error") {
            flushSync(() => {
              setThinking(false);
              setMessages((prev) => [
                ...prev,
                {
                  id: assistantId,
                  role: "assistant",
                  content: `Something went wrong: ${event.message ?? "unknown error"}`,
                },
              ]);
            });
            break;
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        const msg = err instanceof Error ? err.message : "Unknown error";
        flushSync(() => {
          setThinking(false);
          setMessages((prev) => [
            ...prev,
            {
              id: assistantId,
              role: "assistant",
              content: `Network error: ${msg}`,
            },
          ]);
        });
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, mode]
  );

  const handleSend = useCallback(
    async (question: string, fromSuggestion: boolean = false) => {
      if (atLimit) return;
      if (streaming) return;

      // Suggestion clicks check preloaded cache first
      if (fromSuggestion) {
        const cached = await fetchPreloaded(CLIENT_ID, mode, question);
        if (cached) {
          await deliverPreloaded(question, cached.answer, cached.sources);
          return;
        }
      }

      await runLiveQuery(question);
    },
    [mode, streaming, atLimit, deliverPreloaded, runLiveQuery]
  );

  // ─── Derived display values ────────────────────────────────────────────
  const isCreator = mode === "creator";
  const channelName = client?.channel_name ?? "The Koerner Office";
  const creatorName = client?.creator_name ?? "Chris Koerner";
  const allSuggestions = client
    ? isCreator
      ? client.creator_suggestions
      : client.audience_suggestions
    : [];

  // Filter out suggestions that have already been asked in this conversation.
  // Match on exact question text (trimmed) — same convention the backend uses
  // for cache lookup, so filtering here mirrors what would happen on a hit.
  const askedQuestions = new Set(
    messages.filter((m) => m.role === "user").map((m) => m.content.trim())
  );
  const suggestions = allSuggestions.filter((s) => !askedQuestions.has(s.trim()));

  const eyebrowText = isCreator
    ? "Creator Mode — Your Archive"
    : `Chatting with ${channelName}`;

  const heroTitle = isCreator ? "Your archive, working for you" : "Channel Brain";

  const emptyStatePrompt = isCreator
    ? "Explore your own archive."
    : `Ask anything about ${channelName}.`;

  return (
    <>
      <Sidebar onNewChat={handleNewChat} />

      <main className="md:ml-[180px] pb-24 md:pb-8">
        {/* ─── Section 1: Chat ─────────────────────────────── */}
        <section
          id="section-chat"
          className="min-h-screen flex flex-col items-center px-4"
        >
          <div className="w-full max-w-3xl pt-10 pb-4 text-center">
            <div className="text-4xl mb-3">🧠</div>
            <h1 className="font-serif text-5xl font-black text-fg-primary">
              {heroTitle}
            </h1>
            <p
              className="font-mono text-xs tracking-[0.2em] uppercase mt-2"
              style={{ color: "var(--accent)" }}
            >
              {eyebrowText}
            </p>
            {clientError && (
              <p className="mt-3 text-xs text-red-400">
                Client load error: {clientError}
              </p>
            )}
          </div>

          <div
            ref={scrollRef}
            className={`w-full max-w-3xl overflow-y-auto pb-4 min-h-0 ${messages.length === 0 && !thinking ? "" : "flex-1"}`}
            style={{ maxHeight: "calc(100vh - 320px)" }}
          >
            {messages.length === 0 && !thinking && (
              <div className="text-center text-fg-faint text-sm pt-4 pb-6">
                {emptyStatePrompt}
                {suggestions.length > 0 && (
                  <div className="mt-1 text-xs">
                    Try one of the questions below, or type your own.
                  </div>
                )}
              </div>
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} />
            ))}
            {thinking && <ThinkingIndicator />}
          </div>

          <div className="w-full max-w-3xl pb-6 pt-2 border-t border-border-subtle">
            {/* Persistent suggestions above the input — encourages preloaded
                clicks over write-ins, which keeps costs down and answer
                quality consistently high. */}
            {suggestions.length > 0 && !atLimit && (
              <Suggestions
                suggestions={suggestions}
                onClick={(s) => handleSend(s, true)}
                disabled={streaming}
              />
            )}
            {/* Turn-limit warnings */}
            {!atLimit && remaining <= WARN_TURNS_REMAINING && turnCount > 0 && (
              <p className="text-center text-xs mb-2" style={{ color: "var(--accent)" }}>
                {remaining} {remaining === 1 ? "question" : "questions"} left in this conversation
              </p>
            )}
            {atLimit && (
              <div className="text-center text-xs mb-3 py-2 px-4 bg-bg-panel border border-border-strong rounded-lg">
                <span className="text-fg-secondary">
                  Conversation limit reached.
                </span>{" "}
                <button
                  onClick={handleNewChat}
                  className="underline hover:no-underline"
                  style={{ color: "var(--accent)" }}
                >
                  Start a new one →
                </button>
              </div>
            )}
            <ChatInput
              onSend={(q) => handleSend(q, false)}
              disabled={streaming || atLimit}
              placeholder={atLimit ? "Start a new chat to continue..." : "Ask anything..."}
            />
            <p className="text-center text-[10px] text-fg-dim mt-2 leading-relaxed">
              AI-generated from public YouTube content. May contain inaccuracies.
              For educational purposes only. Not affiliated with or endorsed by {creatorName}.
            </p>
          </div>
        </section>

        {/* ─── Section 2: Creator Mode ─────────────────────── */}
        <section
          id="section-creator-mode"
          className="min-h-[70vh] max-w-3xl mx-auto px-4 py-16"
        >
          <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-accent-creator mb-2">
            🎨 Creator Mode
          </p>
          <h2 className="font-serif text-3xl font-bold text-fg-primary mb-4">
            Your archive becomes a tool you can use, too
          </h2>
          <p className="text-fg-secondary text-base leading-relaxed mb-6">
            Creator Mode turns your own video archive into a strategic mirror.
            Ask what patterns you keep returning to, pull quotable moments, spot
            gaps in what you&apos;ve covered.
          </p>
          <div className="bg-bg-panel border-l-4 border-accent-creator rounded-r-lg p-6">
            <p className="text-fg-secondary text-sm mb-4">
              Toggle Creator Mode to shift the demo above into first-person
              analysis of your own archive.
            </p>
            <ModeToggle
              mode={mode}
              onChange={handleModeChange}
              disabled={streaming}
            />
          </div>
        </section>

        {/* ─── Section 3: How it works ─────────────────────── */}
        <section
          id="section-how"
          className="min-h-[70vh] max-w-3xl mx-auto px-4 py-16"
        >
          <p
            className="font-mono text-[10px] tracking-[0.2em] uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            ⚡ How it works
          </p>
          <h2 className="font-serif text-3xl font-bold text-fg-primary mb-8">
            From YouTube archive to conversational AI
          </h2>
          <div className="space-y-6">
            {[
              { num: 1, title: "We index your channel", body: "Every video transcript is pulled, chunked, and stored in a searchable database." },
              { num: 2, title: "Your audience asks questions", body: "They type any question in plain English, just like texting you directly." },
              { num: 3, title: "AI answers from your content", body: "Answers sourced only from your videos, with links back to the source episode." },
            ].map((step) => (
              <div key={step.num} className="flex items-start gap-4">
                <div
                  className="shrink-0 w-9 h-9 rounded-full text-bg-base font-bold flex items-center justify-center"
                  style={{ background: "var(--accent)" }}
                >
                  {step.num}
                </div>
                <div>
                  <div className="font-semibold text-fg-primary text-base mb-1">
                    {step.title}
                  </div>
                  <div className="text-fg-muted text-sm leading-relaxed">
                    {step.body}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ─── Section 4: Get yours ─────────────────────────── */}
        <section
          id="section-get-yours"
          className="min-h-[70vh] max-w-3xl mx-auto px-4 py-16"
        >
          <p
            className="font-mono text-[10px] tracking-[0.2em] uppercase mb-2"
            style={{ color: "var(--accent)" }}
          >
            📩 Get yours
          </p>
          <h2 className="font-serif text-3xl font-bold text-fg-primary mb-4">
            Live on your site in under a week
          </h2>
          <p className="text-fg-secondary text-base leading-relaxed mb-6">
            What you just tried? We build that for your channel. Trained on your
            content, branded for your audience, live on your website in under a
            week.
          </p>
          <div className="bg-bg-panel border border-border-default rounded-lg p-6 mb-4">
            <p className="text-fg-secondary text-sm mb-1 leading-relaxed">
              Tell us where to reach you and where your channel lives. We&apos;ll
              get back within 48 hours.
            </p>
          </div>
          <LeadForm clientId={CLIENT_ID} />
        </section>

        <footer className="max-w-3xl mx-auto px-4 py-8 text-center">
          <p className="text-fg-dim text-[11px] leading-relaxed">
            Channel Brain is an AI assistant trained on {creatorName}&apos;s
            public YouTube content. Responses are for educational purposes only
            and may contain inaccuracies. Not affiliated with or endorsed by the
            creator unless stated otherwise.
          </p>
        </footer>
      </main>
    </>
  );
}
