import { useEffect, useRef, useState } from "react";
import { type Me, api, messageFor } from "./api";
import { useLang } from "./i18n";

type Props = { me: Me; onDeleted: () => void };

/** Phone, consent, download and delete-my-data: one strip, shown on Profile (patients) or the dashboard. */
export function Account({ me, onDeleted }: Props) {
  const { lang, t } = useLang();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);

  // The button that had focus unmounts when the confirm opens or closes; move focus on purpose.
  useEffect(() => {
    if (confirming) keepRef.current?.focus();
    else if (opened.current) deleteRef.current?.focus();
    opened.current = confirming || opened.current;
  }, [confirming]);

  async function deleteAll() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteMe();
      onDeleted();
    } catch (e) {
      setError(messageFor(e, lang));
      setBusy(false);
    }
  }

  return (
    <section className="strip" aria-labelledby="account-title">
      <div className="strip__head">
        <h2 className="strip__title" id="account-title">{t("yourAccount")}</h2>
      </div>
      <dl className="batch">
        <div>
          <dt>{t("phone")}</dt>
          <dd>{me.phone_masked}</dd>
        </div>
        <div>
          <dt>{t("consent")}</dt>
          <dd>{t(me.consent.core ? "given" : "notGiven")}</dd>
        </div>
      </dl>
      <div className="strip__body">
        {error && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {error}
          </div>
        )}
        {confirming ? (
          <div role="group" aria-labelledby="delete-q">
            <p id="delete-q">
              <strong>{t("deleteQ")}</strong> {t("deleteBody")}
            </p>
            <div className="actions">
              <button className="btn btn--danger" onClick={deleteAll} disabled={busy} aria-busy={busy}>
                {busy ? t("deleting") : t("yesDelete")}
              </button>
              <button ref={keepRef} className="btn btn--quiet" onClick={() => setConfirming(false)} disabled={busy}>
                {t("keepData")}
              </button>
            </div>
          </div>
        ) : (
          <div className="actions">
            <a className="btn btn--quiet" href={api.exportUrl} download>
              {t("download")}
            </a>
            <button ref={deleteRef} className="btn btn--quiet" onClick={() => setConfirming(true)}>
              {t("deleteData")}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
