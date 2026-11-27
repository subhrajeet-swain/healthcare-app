import { useCallback, useEffect, useState } from "react";
import { type TgLink, type TgLinkCode, api, messageFor } from "./api";
import { useLang } from "./i18n";

/** Profile strip: connect the patient's Telegram through the bot's deep link, see the status, unlink. */
export function Telegram() {
  const { lang, t } = useLang();
  const [status, setStatus] = useState<TgLink | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.channelLink<TgLink>("telegram");
      setStatus(s);
      if (s.linked) setWaiting(false);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The patient taps Start in Telegram: on coming back, check whether it linked.
  useEffect(() => {
    if (!waiting) return;
    const back = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [waiting, load]);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const connect = () =>
    act(async () => {
      const { url } = await api.channelLinkCode<TgLinkCode>("telegram", lang);
      setWaiting(true);
      window.location.assign(url);
    });
  const unlink = () =>
    act(async () => {
      await api.channelUnlink("telegram");
      setWaiting(false);
      await load();
    });

  const actions =
    status === null || !status.available ? null : status.linked ? (
      <button className="btn btn--quiet" onClick={unlink} disabled={busy} aria-busy={busy}>
        {t("tgUnlink")}
      </button>
    ) : (
      <button className="btn" onClick={connect} disabled={busy} aria-busy={busy}>
        {t("tgConnect")}
      </button>
    );

  return (
    <section className="strip" aria-labelledby="tg-title">
      <div className="strip__head">
        <h2 className="strip__title" id="tg-title">{t("tgTitle")}</h2>
      </div>
      <div aria-live="polite">
        {status !== null && (
          <div className="strip__body">
            {!status.available ? (
              <p className="field__hint">{t("tgUnavailable")}</p>
            ) : status.linked ? (
              <>
                <p>{t("tgLinked")}</p>
                {!status.opted_in && <p className="field__hint">{t("tgOptedOut")}</p>}
              </>
            ) : (
              <p className="field__hint">{t("tgLede")}</p>
            )}
          </div>
        )}
      </div>
      {(error !== null || actions) && (
        <div className="strip__body">
          {error !== null && (
            <div className="msg msg--error" role="alert">
              <strong>{t("problem")}</strong>
              {messageFor(error, lang)}
            </div>
          )}
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
    </section>
  );
}
