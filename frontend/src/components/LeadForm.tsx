"use client";

import { useState } from "react";
import { submitLead } from "@/lib/api";

interface Props {
  clientId: string;
}

type State = "idle" | "submitting" | "success" | "error";

export function LeadForm({ clientId }: Props) {
  const [email, setEmail] = useState("");
  const [channelUrl, setChannelUrl] = useState("");
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<State>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async () => {
    setErrorMsg(null);
    if (!email.trim()) {
      setErrorMsg("Email is required");
      return;
    }
    if (!consent) {
      setErrorMsg("Please agree to be contacted");
      return;
    }
    setState("submitting");
    try {
      await submitLead({
        email: email.trim(),
        channel_url: channelUrl.trim(),
        client_id: clientId,
        consent,
      });
      setState("success");
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : "Submission failed");
    }
  };

  if (state === "success") {
    return (
      <div className="bg-bg-panel border border-border-default rounded-lg p-6">
        <div className="text-3xl mb-3">✓</div>
        <div className="font-serif text-xl font-bold text-fg-primary mb-2">
          You&apos;re on the list
        </div>
        <p className="text-fg-secondary text-sm leading-relaxed mb-6">
          We&apos;ll be in touch within 48 hours to discuss your channel.
          In the meantime, here&apos;s what to expect.
        </p>

        {/* Pricing revealed */}
        <div className="border-t border-border-subtle pt-6">
          <div className="font-mono text-[10px] tracking-widest uppercase text-fg-muted mb-3">
            💰 Pricing
          </div>
          <div className="flex items-baseline gap-2 mb-3">
            <span
              className="font-serif text-3xl font-bold"
              style={{ color: "var(--accent)" }}
            >
              $497
            </span>
            <span className="text-fg-muted text-sm">/ month</span>
          </div>
          <ul className="text-fg-secondary text-sm space-y-1.5">
            <li>→ We index your full video catalog</li>
            <li>→ Unlimited queries from your audience</li>
            <li>→ Embed on your site or membership</li>
            <li>→ Creator Mode for your own use</li>
            <li>→ Live in under a week</li>
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-bg-panel border border-border-default rounded-lg p-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (state !== "submitting") handleSubmit();
        }}
        className="space-y-3"
      >
        <div>
          <label className="block text-xs font-mono uppercase tracking-widest text-fg-muted mb-1.5">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={state === "submitting"}
            placeholder="you@example.com"
            className="w-full bg-bg-input border border-border-input rounded-lg px-3 py-2.5 text-sm text-fg-primary placeholder:text-fg-dim focus:outline-none focus:border-[color:var(--accent)] disabled:opacity-50"
          />
        </div>

        <div>
          <label className="block text-xs font-mono uppercase tracking-widest text-fg-muted mb-1.5">
            YouTube channel <span className="normal-case text-fg-dim">(optional)</span>
          </label>
          <input
            type="text"
            value={channelUrl}
            onChange={(e) => setChannelUrl(e.target.value)}
            disabled={state === "submitting"}
            placeholder="youtube.com/@yourchannel"
            className="w-full bg-bg-input border border-border-input rounded-lg px-3 py-2.5 text-sm text-fg-primary placeholder:text-fg-dim focus:outline-none focus:border-[color:var(--accent)] disabled:opacity-50"
          />
        </div>

        <label className="flex items-start gap-2.5 pt-2 cursor-pointer group">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            disabled={state === "submitting"}
            className="mt-0.5 shrink-0 w-4 h-4 accent-[color:var(--accent)]"
          />
          <span className="text-xs text-fg-muted leading-relaxed group-hover:text-fg-secondary">
            I agree to be contacted by Channel Brain about this inquiry. My email
            won&apos;t be shared or used for other marketing.
          </span>
        </label>

        {errorMsg && (
          <p className="text-xs text-red-400 mt-2">{errorMsg}</p>
        )}

        <button
          type="submit"
          disabled={state === "submitting"}
          className="w-full mt-2 bg-accent-creator hover:bg-accent-creator-hover disabled:opacity-40 disabled:cursor-not-allowed text-bg-base font-semibold text-sm px-5 py-3 rounded-lg transition-colors"
        >
          {state === "submitting" ? "Submitting..." : "Request a demo →"}
        </button>
      </form>
    </div>
  );
}
