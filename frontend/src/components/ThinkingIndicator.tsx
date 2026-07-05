"use client";

export function ThinkingIndicator() {
  return (
    <div className="flex items-start gap-3 my-3">
      <div className="text-xl mt-0.5">🧠</div>
      <div
        className="bg-bg-input rounded-r-lg px-4 py-3 flex items-center gap-4"
        style={{ borderLeft: "3px solid var(--accent)" }}
      >
        <div className="text-fg-muted text-xs font-mono uppercase tracking-widest">
          Searching the archive
        </div>
        <div className="flex gap-1.5 items-center">
          {[0, 0.4, 0.8].map((delay, i) => (
            <span
              key={i}
              className="w-[7px] h-[7px] rounded-full"
              style={{
                background: "var(--accent)",
                animation: `tpulse 1.2s ${delay}s infinite`,
              }}
            />
          ))}
        </div>
      </div>

      <style jsx>{`
        @keyframes tpulse {
          0%,
          100% {
            opacity: 0.2;
            transform: scale(0.7);
          }
          50% {
            opacity: 1;
            transform: scale(1.1);
          }
        }
      `}</style>
    </div>
  );
}
