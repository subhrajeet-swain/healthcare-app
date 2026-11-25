import { useState } from "react";
import { CONSENT_VERSION, api, messageFor } from "../api";
import { Band } from "../Band";
import { type Key, useLang } from "../i18n";

type Props = { onAgreed: () => Promise<void>; onSignOut: () => void };

const STATEMENTS: Key[] = ["consent1", "consent2", "consent3"];

export function Consent({ onAgreed, onSignOut }: Props) {
  const { lang, t } = useLang();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function agree() {
    setBusy(true);
    setError(null);
    try {
      await api.grantConsent();
      await onAgreed();
    } catch (e) {
      setError(messageFor(e, lang));
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>{t("beforeStart")}</h1>
        <p className="lede">{t("consentLede")}</p>

        {error && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {error}
          </div>
        )}

        <section className="strip" aria-labelledby="consent-title">
          <div className="strip__head">
            <h2 className="strip__title" id="consent-title">
              {t("yourChoice")}
            </h2>
          </div>
          <ul className="perf-list">
            {STATEMENTS.map((k) => (
              <li key={k}>{t(k)}</li>
            ))}
          </ul>
          <dl className="batch">
            <div>
              <dt>{t("purpose")}</dt>
              <dd>{t("coreService")}</dd>
            </div>
            <div>
              <dt>{t("version")}</dt>
              <dd>{CONSENT_VERSION}</dd>
            </div>
          </dl>
        </section>

        <div className="actions">
          <button className="btn" onClick={agree} disabled={busy} aria-busy={busy}>
            {busy ? t("saving") : t("agree")}
          </button>
          <button className="btn btn--quiet" onClick={onSignOut} disabled={busy}>
            {t("notNow")}
          </button>
        </div>
      </main>
    </div>
  );
}
