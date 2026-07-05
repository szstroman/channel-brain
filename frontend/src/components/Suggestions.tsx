"use client";

interface Props {
  suggestions: string[];
  onClick: (s: string) => void;
  disabled: boolean;
}

export function Suggestions({ suggestions, onClick, disabled }: Props) {
  if (suggestions.length === 0) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onClick(s)}
          disabled={disabled}
          className="text-left text-sm bg-bg-panel border border-border-strong text-fg-secondary rounded-lg px-4 py-2.5 hover:border-[color:var(--accent)] hover:text-fg-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
