import { useState } from "react";
import { CONSENT_VERSION, api, messageFor } from "../api";
import { Band } from "../Band";

type Props = { onAgreed: () => void; onSignOut: () => void };

export function Consent({ onAgreed, onSignOut }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function agree() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent();
      onAgreed();
    } catch (e) {
      setError(messageFor(e));
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>Before we start</h1>
        <p className="lede">Read how we handle your health data. You can change your mind at any time.</p>

        {error && (
          <div className="msg msg--error" role="alert">
            <strong>Problem</strong>
            {error}
          </div>
        )}

        <section className="strip" aria-labelledby="consent-title">
          <div className="strip__head">
            <h2 className="strip__title" id="consent-title">Your data, your choice</h2>
          </div>
          <ul className="perf-list">
            <li>We keep your reports and phone number encrypted. Only your lab and its doctors can see them.</li>
            <li>We explain your reports in plain language. A doctor decides anything about treatment.</li>
            <li>You can download all your data, or delete it, from your home screen.</li>
          </ul>
          <dl className="batch">
            <div>
              <dt>Purpose</dt>
              <dd>Core service</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{CONSENT_VERSION}</dd>
            </div>
          </dl>
        </section>

        <div className="actions">
          <button className="btn" onClick={agree} disabled={busy}>
            {busy ? "Saving…" : "I agree"}
          </button>
          <button className="btn btn--quiet" onClick={onSignOut} disabled={busy}>
            Not now, sign out
          </button>
        </div>
      </main>
    </div>
  );
}
