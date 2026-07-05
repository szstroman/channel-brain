"use client";

import { useState, useRef, KeyboardEvent } from "react";

interface Props {
  onSend: (question: string) => void;
  disabled: boolean;
  placeholder: string;
}

export function ChatInput({ onSend, disabled, placeholder }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex gap-2 items-end">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          const el = e.currentTarget;
          el.style.height = "auto";
          el.style.height = Math.min(el.scrollHeight, 120) + "px";
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="flex-1 bg-bg-input border border-border-input rounded-lg text-fg-primary placeholder:text-fg-dim text-sm px-4 py-3 resize-none focus:outline-none focus:border-[color:var(--accent)] disabled:opacity-50"
        style={{ maxHeight: 120 }}
      />
      <button
        onClick={submit}
        disabled={disabled || !value.trim()}
        className="disabled:opacity-40 disabled:cursor-not-allowed text-bg-base font-semibold text-sm px-5 py-3 rounded-lg transition-opacity whitespace-nowrap hover:opacity-90"
        style={{ background: "var(--accent)" }}
      >
        Ask →
      </button>
    </div>
  );
}
