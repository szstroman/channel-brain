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
const DEFAULT_CLIENT_ID = "koerner-office";

// Resolve the client to demo from the URL. Supports:
//   /              → koerner-office (default)
//   /?client=X     → X
//   /?c=X          → X (short form)
// Falls back to default on server (during SSR) since window isn't defined there.
function resolveClientId(): string {
  if (typeof window === "undefined") return DEFAULT_CLIENT_ID;
  const params = new URLSearchParams(window.location.search);
  const cid = params.get("client") || params.get("c");
  return cid?.trim() || DEFAULT_CLIENT_ID;
}

// Resolve the starting mode from the URL. Supports:
//   /?mode=creator   → creator mode active on load (used in outreach links so
//                      the recipient — the creator evaluating for their own
//                      business — lands in the mode built for them)
//   anything else    → audience (default)
// Same SSR-safe lazy-initializer pattern as resolveClientId: server renders
// "audience", client first paint resolves the param, no flash.
function resolveInitialMode(): Mode {
  if (typeof window === "undefined") return "audience";
  const params = new URLSearchParams(window.location.search);
  return params.get("mode")?.trim().toLowerCase() === "creator"
    ? "creator"
    : "audience";
}
const MAX_TURNS = 8; // Each turn = 1 user + 1 assistant. So 8 user messages max.
const WARN_TURNS_REMAINING = 2;

function makeId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function countUserTurns(messages: Message[]): number {
  return messages.filter((m) => m.role === "user").length;
}

export default function Home() {
  // Resolve which client to demo from the URL exactly once, at first render.
  // useState's lazy initializer runs only on the initial render (not on every
  // re-render), so this is efficient. Combined with resolveClientId's SSR guard
  // (returns DEFAULT_CLIENT_ID on server), this ensures:
  //   - On server: renders with DEFAULT_CLIENT_ID
  //   - On client first paint: renders with URL-derived client
  //   - No flash from Koerner → Ken because we skip the useEffect-based swap
  const [clientId] = useState<string>(() => resolveClientId());
  // Mode is resolved AFTER mount, unlike clientId. Reason: clientId only
  // affects async-fetched data (server HTML and first client paint are
  // identical either way), but mode immediately changes rendered text — hero
  // title, card states, palette. A lazy initializer would make the client's
  // first render diverge from the server HTML on ?mode=creator links, and
  // React 19 logs hydration errors for that. Resolving in an effect means one
  // imperceptible audience→creator frame at load instead of console errors.
  const [mode, setMode] = useState<Mode>("audience");
  useEffect(() => {
    const urlMode = resolveInitialMode();
    if (urlMode !== "audience") setMode(urlMode);
  }, []);
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
    fetchClient(clientId)
      .then(setClient)
      .catch((e) => {
        setClientError(e instanceof Error ? e.message : "Failed to load client");
      });
  }, [clientId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, thinking]);

  // Separate mobile auto-scroll effect: only fires when a NEW message is added
  // or the thinking indicator toggles. Token updates change message.content but
  // don't change messages.length, so this effect skips them — no scroll jitter
  // during streaming.
  const messageCount = messages.length;
  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 768) return;
    if (messageCount === 0 && !thinking) return;
    const t = setTimeout(() => {
      const chatSection = document.getElementById("section-chat");
      if (chatSection) {
        chatSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, 100);
    return () => clearTimeout(t);
  }, [messageCount, thinking]);

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

  // Role-card mode selection in the hero. Same reset as handleModeChange but
  // WITHOUT the scroll-back — the visitor is already at the top of the chat
  // section, so scrolling would just produce a jarring jump.
  const selectMode = useCallback((newMode: Mode) => {
    abortRef.current?.abort();
    setMode(newMode);
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
      // After a beat (so the visitor sees the toggle animate + palette change),
      // scroll back up to the chat so they can try the new mode without hunting.
      // 800ms lets both the toggle switch animation (~200ms) and the palette
      // swap fully register before we scroll.
      setTimeout(() => {
        const chatSection = document.getElementById("section-chat");
        if (chatSection) {
          chatSection.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }, 800);
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
            client_id: clientId,
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
    [messages, mode, clientId]
  );

  const handleSend = useCallback(
    async (question: string, fromSuggestion: boolean = false) => {
      if (atLimit) return;
      if (streaming) return;

      // Suggestion clicks check preloaded cache first
      if (fromSuggestion) {
        const cached = await fetchPreloaded(clientId, mode, question);
        if (cached) {
          await deliverPreloaded(question, cached.answer, cached.sources);
          return;
        }
      }

      await runLiveQuery(question);
    },
    [mode, streaming, atLimit, deliverPreloaded, runLiveQuery, clientId]
  );

  // ─── Derived display values ────────────────────────────────────────────
  const isCreator = mode === "creator";
  // No hard-coded creator fallback: on a personalized link (?client=ken-pozek)
  // the config fetch takes a beat, and a Koerner fallback would flash the WRONG
  // creator's name on another creator's demo — the single most trust-damaging
  // failure for personalized outreach. Neutral text until the config resolves.
  const channelName = client?.channel_name ?? null;

  const eyebrowText = isCreator
    ? channelName
      ? `Creator Mode — ${channelName}'s archive`
      : "Creator Mode"
    : channelName
      ? `Chatting with ${channelName}`
      : clientError
        ? "Channel unavailable"
        : "Loading channel...";

  const heroTitle = isCreator ? "Put your archive to work" : "Channel Brain";

  const emptyStatePrompt = isCreator
    ? "Explore your own archive."
    : channelName
      ? `Ask anything about ${channelName}.`
      : "Ask anything.";

  const allSuggestions = client
    ? isCreator
      ? client.creator_suggestions
      : client.audience_suggestions
    : [];

  // Filter out suggestions that have already been asked in this conversation.
  // Match on exact question text (trimmed) — same convention the backend uses
  // for cache lookup, so filtering here mirrors what would happen on a hit.
  // Cap at 4 suggestions to keep the empty state compact on mobile (visitors
  // shouldn't need to scroll to see the input).
  const askedQuestions = new Set(
    messages.filter((m) => m.role === "user").map((m) => m.content.trim())
  );
  const suggestions = allSuggestions
    .filter((s) => !askedQuestions.has(s.trim()))
    .slice(0, 4);

  return (
    <>
      <Sidebar onNewChat={handleNewChat} />

      <main className="md:ml-[180px] pb-24 md:pb-8">
        {/* ─── Section 1: Chat ─────────────────────────────── */}
        <section
          id="section-chat"
          className="min-h-screen flex flex-col items-center px-4 md:px-8"
        >
          <div className="w-full max-w-4xl pt-10 pb-4 text-center">
            <div className="text-4xl mb-3">🧠</div>
            <h1 className="font-serif text-4xl md:text-6xl font-black text-fg-primary">
              {heroTitle}
            </h1>
            <p
              className="font-mono text-sm md:text-base tracking-[0.2em] uppercase mt-3"
              style={{ color: "var(--accent)" }}
            >
              {eyebrowText}
            </p>
            {messages.length === 0 && !thinking && (
              <p className="text-fg-secondary text-lg md:text-xl mt-4 max-w-2xl mx-auto leading-relaxed">
                Turn a content archive into a business tool. Pick where to
                start:
              </p>
            )}
            {client?.channel_url && (
              <a
                href={client.channel_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block mt-2 text-xs text-fg-muted hover:text-fg-secondary transition-colors"
              >
                Source channel on YouTube ↗
              </a>
            )}
            {clientError && (
              <p className="mt-3 text-sm text-red-400">
                Client load error: {clientError}
              </p>
            )}
          </div>

          <div
            ref={scrollRef}
            className={`w-full max-w-4xl overflow-y-auto pb-4 min-h-0 ${messages.length === 0 && !thinking ? "" : "flex-1"}`}
            style={{ maxHeight: "calc(100vh - 320px)" }}
          >
            {messages.length === 0 && !thinking && (
              <div className="pt-2 pb-6">
                {/* Compact role selector. Both options render at full opacity
                    so neither reads as disabled; the active one gets a colored
                    border + dot. Two columns even on mobile to keep the chat
                    input above the fold. */}
                <div className="grid grid-cols-2 gap-3 mb-5">
                  <button
                    onClick={() => selectMode("creator")}
                    className="text-left bg-bg-panel border-2 rounded-lg p-3.5 md:p-5 transition-colors hover:bg-bg-input"
                    style={{ borderColor: isCreator ? "#d4a359" : "var(--border-strong, #333)" }}
                  >
                    <div className="font-mono text-[10px] tracking-widest uppercase mb-1" style={{ color: "#d4a359" }}>
                      {isCreator ? "● " : ""}Creator Mode
                    </div>
                    <h3 className="font-semibold text-fg-primary text-base md:text-lg mb-0.5">
                      For you and your team
                    </h3>
                    <p className="text-fg-muted text-xs md:text-sm leading-snug">
                      Plan &middot; Research &middot; Repurpose
                    </p>
                  </button>

                  <button
                    onClick={() => selectMode("audience")}
                    className="text-left bg-bg-panel border-2 rounded-lg p-3.5 md:p-5 transition-colors hover:bg-bg-input"
                    style={{ borderColor: !isCreator ? "#5eb8ff" : "var(--border-strong, #333)" }}
                  >
                    <div className="font-mono text-[10px] tracking-widest uppercase mb-1" style={{ color: "#5eb8ff" }}>
                      {!isCreator ? "● " : ""}Audience Mode
                    </div>
                    <h3 className="font-semibold text-fg-primary text-base md:text-lg mb-0.5">
                      For your audience
                    </h3>
                    <p className="text-fg-muted text-xs md:text-sm leading-snug">
                      Answer &middot; Recommend &middot; Convert
                    </p>
                  </button>
                </div>

                <div className="text-center text-fg-muted text-base md:text-lg">
                  {emptyStatePrompt}
                  {suggestions.length > 0 && (
                    <div className="mt-2 text-sm md:text-base text-fg-muted">
                      Try one of the questions below, or type your own.
                    </div>
                  )}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <ChatMessage key={m.id} message={m} />
            ))}
            {thinking && <ThinkingIndicator />}
          </div>

          <div className="w-full max-w-4xl pb-6 pt-2 border-t border-border-subtle">
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
            {/* Suggestions BELOW input after first message so the input sits
                directly under the answer stream. Above input in the empty
                state so they're the first thing a visitor sees. */}
            {suggestions.length > 0 && !atLimit && (
              <div className="mt-3">
                <Suggestions
                  suggestions={suggestions}
                  onClick={(s) => handleSend(s, true)}
                  disabled={streaming}
                />
              </div>
            )}
            <p className="text-center text-xs text-fg-muted mt-2 leading-relaxed">
              AI-generated from public YouTube content. May contain inaccuracies.
              For educational purposes only. Not affiliated with or endorsed by the source channel.
            </p>

            {/* Primary conversion CTA — directly under the demo so the
                "this is interesting" moment has an immediate next step,
                instead of living several screens down the page. */}
            <div className="mt-6 bg-bg-panel border border-border-strong rounded-lg p-5 md:p-6 text-center">
              <p className="text-fg-primary font-semibold text-lg md:text-xl mb-1">
                See this built for your channel
              </p>
              <p className="text-fg-muted text-sm md:text-base mb-4">
                Done-for-you setup. Working version in under a week.
              </p>
              <a
                href="#section-get-yours"
                onClick={(e) => {
                  e.preventDefault();
                  document
                    .getElementById("section-get-yours")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className="inline-block font-semibold text-sm md:text-base px-6 py-3 rounded-lg text-bg-base hover:opacity-90 transition-opacity"
                style={{ background: "#d4a359" }}
              >
                Get my channel demo →
              </a>
            </div>
          </div>
        </section>

        {/* ─── Section 2: Creator Mode ─────────────────────── */}
        <section
          id="section-creator-mode"
          className="max-w-4xl mx-auto px-4 md:px-8 py-12 md:py-16"
        >
          <p className="font-mono text-xs tracking-[0.2em] uppercase text-accent-creator mb-3">
            🎨 Creator Mode
          </p>
          <h2 className="font-serif text-3xl md:text-5xl font-bold text-fg-primary mb-6 leading-tight">
            Your team can finally use everything you&apos;ve published
          </h2>
          <p className="text-fg-secondary text-lg md:text-xl leading-relaxed mb-6 max-w-3xl">
            Search every idea, example, and opinion you have published. Use it
            to plan new content, repurpose old material, train your team, and
            keep your messaging consistent.
          </p>
          <div className="bg-bg-panel border-l-4 border-accent-creator rounded-r-lg p-6 md:p-8 max-w-3xl">
            <p className="text-fg-secondary text-base md:text-lg mb-4">
              Switch the demo above between modes any time:
            </p>
            <ModeToggle
              mode={mode}
              onChange={handleModeChange}
              disabled={streaming}
            />
          </div>

          {/* Roadmap: one line only. Selling what exists today — unbuilt
              features stay out of the conversion path. */}
          <p className="text-fg-muted text-sm md:text-base mt-6 max-w-3xl">
            Coming next: comment intelligence and multi-source archives
            (podcast, newsletter, blog).
          </p>
        </section>

        {/* ─── Section 3: How it works ─────────────────────── */}
        <section
          id="section-how"
          className="max-w-4xl mx-auto px-4 md:px-8 py-12 md:py-16"
        >
          <p
            className="font-mono text-xs tracking-[0.2em] uppercase mb-3"
            style={{ color: "#d4a359" }}
          >
            ⚡ How it works
          </p>
          <h2 className="font-serif text-3xl md:text-5xl font-bold text-fg-primary mb-10 leading-tight">
            From YouTube archive to conversational AI
          </h2>
          <div className="space-y-8">
            {[
              { num: 1, title: "We index your channel", body: "Every video you've published becomes instantly searchable." },
              { num: 2, title: "Your audience asks questions", body: "They type any question in plain English, just like texting you directly." },
              { num: 3, title: "AI answers from your content", body: "Answers sourced only from your videos, with links back to the source episode." },
            ].map((step) => (
              <div key={step.num} className="flex items-start gap-5">
                <div
                  className="shrink-0 w-12 h-12 rounded-full text-bg-base font-bold text-xl flex items-center justify-center"
                  style={{ background: "#d4a359" }}
                >
                  {step.num}
                </div>
                <div>
                  <div className="font-semibold text-fg-primary text-xl md:text-2xl mb-2">
                    {step.title}
                  </div>
                  <div className="text-fg-muted text-base md:text-lg leading-relaxed">
                    {step.body}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ─── Section 3.5: Why not just use YouTube's AI? ────── */}
        <section
          id="section-vs-youtube"
          className="max-w-4xl mx-auto px-4 md:px-8 py-12 md:py-16"
        >
          <p
            className="font-mono text-xs tracking-[0.2em] uppercase mb-3"
            style={{ color: "#d4a359" }}
          >
            🤔 Why not just use YouTube&apos;s AI?
          </p>
          <h2 className="font-serif text-3xl md:text-5xl font-bold text-fg-primary mb-6 leading-tight">
            YouTube&apos;s AI works for YouTube. Channel Brain works for you.
          </h2>
          <p className="text-fg-secondary text-lg md:text-xl leading-relaxed mb-10 max-w-3xl">
            Google just launched Ask YouTube — a great search feature. But it&apos;s
            built for YouTube, not your business. Here&apos;s the difference:
          </p>

          <div className="grid md:grid-cols-3 gap-5">
            {[
              {
                title: "Lives on your site",
                body: "YouTube helps viewers keep watching. Channel Brain lives beside your guides, services, and contact forms — where the next step actually happens.",
              },
              {
                title: "Grounded only in your content",
                body: "Every answer draws from your videos alone, with a link back to the source episode. YouTube's AI blends you with every other creator on the platform.",
              },
              {
                title: "You see the questions",
                body: "Every question visitors ask is yours to learn from — what they're researching, what they can't find, what they care about. YouTube keeps that data.",
              },
            ].map((point, i) => (
              <div
                key={i}
                className="bg-bg-panel border border-border-strong rounded-lg p-6 md:p-7"
              >
                <div className="flex items-start gap-3 mb-2">
                  <span
                    className="shrink-0 font-serif text-2xl font-bold"
                    style={{ color: "#d4a359" }}
                  >
                    ✓
                  </span>
                  <h3 className="font-semibold text-fg-primary text-lg md:text-xl leading-snug">
                    {point.title}
                  </h3>
                </div>
                <p className="text-fg-muted text-base md:text-lg leading-relaxed pl-9">
                  {point.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* ─── Section 4: Get yours ─────────────────────────── */}
        <section
          id="section-get-yours"
          className="max-w-4xl mx-auto px-4 md:px-8 py-12 md:py-16"
        >
          <p
            className="font-mono text-xs tracking-[0.2em] uppercase mb-3"
            style={{ color: "#d4a359" }}
          >
            📩 Get yours
          </p>
          <h2 className="font-serif text-3xl md:text-5xl font-bold text-fg-primary mb-6 leading-tight">
            Live on your site in under a week
          </h2>
          <p className="text-fg-secondary text-lg md:text-xl leading-relaxed mb-8 max-w-3xl">
            What you just tried? We build that for your channel. Trained on your
            content, branded for your audience, live on your website in under a
            week.
          </p>
          <div className="bg-bg-panel border border-border-default rounded-lg p-6 md:p-8 mb-6 max-w-3xl">
            <p className="text-fg-secondary text-base md:text-lg leading-relaxed">
              Tell us where to reach you and where your channel lives. We&apos;ll
              get back within 48 hours.
            </p>
          </div>
          <div className="max-w-3xl">
            <LeadForm clientId={clientId} />
          </div>
        </section>

        <footer className="max-w-4xl mx-auto px-4 md:px-8 py-10 md:py-12 text-center">
          <p className="text-fg-muted text-sm md:text-base leading-relaxed">
            Channel Brain is an AI assistant trained on a creator&apos;s public
            YouTube content. Responses are for educational purposes only and may
            contain inaccuracies. Not affiliated with or endorsed by the source
            channel unless stated otherwise.
          </p>
        </footer>
      </main>
    </>
  );
}
