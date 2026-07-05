"use client";

import type { Mode } from "@/lib/types";

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
  disabled: boolean;
}

export function ModeToggle({ mode, onChange, disabled }: Props) {
  const isCreator = mode === "creator";
  return (
    <button
      onClick={() => onChange(isCreator ? "audience" : "creator")}
      disabled={disabled}
      className="inline-flex items-center gap-3 bg-bg-panel border border-border-strong rounded-lg px-4 py-3 hover:border-accent-creator transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <span
        className={`relative inline-block w-11 h-6 rounded-full transition-colors ${
          isCreator ? "bg-accent-creator" : "bg-border-strong"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-bg-base transition-transform ${
            isCreator ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </span>
      <span className="font-semibold text-sm text-fg-primary">
        🎨 {isCreator ? "Creator Mode is on" : "Try Creator Mode"}
      </span>
    </button>
  );
}
