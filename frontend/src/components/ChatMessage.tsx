"use client";

import type { Message } from "@/lib/types";

interface Props {
  message: Message;
}

export function ChatMessage({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end my-3">
        <div className="max-w-[85%] bg-bg-card border border-border-strong text-fg-primary rounded-[2px_16px_16px_16px] px-4 py-3 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="my-3">
      <div
        className="bg-bg-panel border border-border-default rounded-[16px_16px_16px_2px] px-4 py-3 text-sm text-fg-secondary leading-relaxed whitespace-pre-wrap"
        style={{ borderLeft: "3px solid var(--accent)" }}
      >
        {message.content}
        {message.streaming && (
          <span className="inline-block w-[2px] h-4 bg-fg-secondary ml-1 animate-pulse align-middle" />
        )}
      </div>

      {message.sources && message.sources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {message.sources.slice(0, 4).map((s, i) => {
            const label = `📹 ${s.title.length > 45 ? s.title.slice(0, 45) + "…" : s.title}`;
            return s.url ? (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block bg-bg-card border border-border-strong text-fg-faint font-mono text-[10px] px-2.5 py-1 rounded-full hover:border-[color:var(--accent)] hover:text-[color:var(--accent)] transition-colors"
              >
                {label}
              </a>
            ) : (
              <span
                key={i}
                className="inline-block bg-bg-card border border-border-strong text-fg-faint font-mono text-[10px] px-2.5 py-1 rounded-full"
              >
                {label}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
