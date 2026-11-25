import { useState } from "react";
import { CONSENT_VERSION, api, messageFor } from "../api";
import { Band } from "../Band";

type Props = { onAgreed: () => Promise<void>; onSignOut: () => void };

// Hindi lines are machine-drafted; a native speaker must review them before real users.
const STATEMENTS: [string, string][] = [
  [
    "Your phone number and name are stored encrypted. Only your lab and its doctors can see your data.",
    "आपका फ़ोन नंबर और नाम एन्क्रिप्ट करके रखा जाता है। आपका डेटा केवल आपकी लैब और उसके डॉक्टर देख सकते हैं।",
  ],
  [
    "We explain your reports in plain language. A doctor decides anything about treatment.",
    "हम आपकी रिपोर्ट आसान भाषा में समझाते हैं। इलाज से जुड़ा हर फ़ैसला डॉक्टर लेते हैं।",
  ],
  [
    "You can download all your data, or delete it, from your home screen.",
    "आप होम स्क्रीन से अपना सारा डेटा डाउनलोड या डिलीट कर सकते हैं।",
  ],
];

export function Consent({ onAgreed, onSignOut }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function agree() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent();
      await onAgreed();
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
        <p className="lede">
          Read how we handle your health data. You can change your mind at any time.
          <br />
          <span className="hi" lang="hi">पढ़ें कि हम आपका स्वास्थ्य डेटा कैसे संभालते हैं। आप कभी भी अपना फ़ैसला बदल सकते हैं।</span>
        </p>

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
            {STATEMENTS.map(([en, hi]) => (
              <li key={en}>
                {en}
                <span className="perf-list__hi hi" lang="hi">{hi}</span>
              </li>
            ))}
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
          <button className="btn" onClick={agree} disabled={busy} aria-busy={busy}>
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
