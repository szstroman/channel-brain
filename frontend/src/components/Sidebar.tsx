"use client";

import { useEffect, useState } from "react";

interface SidebarItem {
  id: string;
  icon: string;
  label: string;
  action: "scroll" | "new-chat";
  target?: string;
}

const ITEMS: SidebarItem[] = [
  { id: "new-chat", icon: "✏️", label: "New chat", action: "new-chat" },
  { id: "chat", icon: "💬", label: "Chat", action: "scroll", target: "section-chat" },
  { id: "creator-mode", icon: "🎨", label: "Creator Mode", action: "scroll", target: "section-creator-mode" },
  // divider
  { id: "how", icon: "⚡", label: "How it works", action: "scroll", target: "section-how" },
  { id: "get-yours", icon: "📩", label: "Get yours", action: "scroll", target: "section-get-yours" },
];

interface Props {
  onNewChat: () => void;
}

export function Sidebar({ onNewChat }: Props) {
  const [activeId, setActiveId] = useState<string>("chat");

  // Track which section is in view — used to highlight the active sidebar item.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Prefer the entry closest to the top of the viewport
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const topId = visible[0].target.id.replace("section-", "");
        setActiveId(topId);
      },
      { rootMargin: "-40% 0px -50% 0px", threshold: 0 }
    );

    ITEMS.forEach((item) => {
      if (item.action === "scroll" && item.target) {
        const el = document.getElementById(item.target);
        if (el) observer.observe(el);
      }
    });

    return () => observer.disconnect();
  }, []);

  const handleClick = (item: SidebarItem) => {
    if (item.action === "new-chat") {
      onNewChat();
      // After clearing, scroll back to the chat section
      const el = document.getElementById("section-chat");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (item.action === "scroll" && item.target) {
      const el = document.getElementById(item.target);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:flex fixed left-0 top-0 h-screen w-[180px] flex-col bg-bg-sidebar border-r border-border-default z-10">
        {/* Brand */}
        <div className="flex items-center gap-2 px-4 py-4 border-b border-border-subtle">
          <span className="text-xl">🧠</span>
          <span className="font-serif font-bold text-base text-fg-primary">
            Channel Brain
          </span>
        </div>

        <nav className="flex-1 py-3">
          {ITEMS.map((item, idx) => {
            const isActive = activeId === item.id;
            // Insert a divider before "How it works" — visually separates
            // interactive items from informational ones.
            const showDivider = item.id === "how";
            return (
              <div key={item.id}>
                {showDivider && (
                  <div className="mx-4 my-2 border-t border-border-subtle" />
                )}
                {showDivider && (
                  <div className="px-4 pt-1 pb-2 font-mono text-[9px] tracking-widest uppercase text-fg-dim">
                    Learn more
                  </div>
                )}
                <button
                  onClick={() => handleClick(item)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors ${
                    isActive
                      ? "bg-[color:var(--accent-glow)] text-[color:var(--accent)] border-l-2 border-[color:var(--accent)]"
                      : "text-fg-muted hover:bg-bg-panel hover:text-fg-primary"
                  }`}
                  style={isActive ? { paddingLeft: "14px" } : undefined}
                >
                  <span className="text-base w-4 text-center">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              </div>
            );
          })}
        </nav>
      </aside>

      {/* Mobile bottom bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-10 bg-bg-sidebar border-t border-border-default flex justify-around py-2">
        {ITEMS.filter((i) => ["new-chat", "chat", "creator-mode", "get-yours"].includes(i.id)).map((item) => {
          const isActive = activeId === item.id;
          return (
            <button
              key={item.id}
              onClick={() => handleClick(item)}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded ${
                isActive ? "text-[color:var(--accent)]" : "text-fg-muted"
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              <span className="text-[9px] font-mono uppercase tracking-wide">
                {item.label.split(" ")[0]}
              </span>
            </button>
          );
        })}
      </nav>
    </>
  );
}
