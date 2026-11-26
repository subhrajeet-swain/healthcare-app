import { useCallback, useEffect, useState } from "react";
import { type WaLink, type WaLinkCode, api, messageFor } from "./api";
import { useLang } from "./i18n";
import { linkInstruction } from "./waLink";

/** Profile strip: link the patient's WhatsApp number with a code, see the status, unlink. */
export function WhatsApp() {
  const { lang, t } = useLang();
  const [status, setStatus] = useState<WaLink | null>(null);
  const [code, setCode] = useState<WaLinkCode | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.waLink();
      setStatus(s);
      if (s.linked) setCode(null);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The patient sends the code from the WhatsApp app: on coming back, check whether it linked.
  useEffect(() => {
    if (!code) return;
    const back = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [code, load]);

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

  const getCode = () =>
    act(async () => {
      setCopied(false);
      setCode(await api.waLinkCode(lang));
    });
  const unlink = () =>
    act(async () => {
      await api.waUnlink();
      setCode(null);
      await load();
    });

  const text = code ? linkInstruction(code.code, code.lab_number) : "";
  async function copy() {
    if (!navigator.clipboard) return; // no clipboard here: the code is on screen to type
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* blocked: same */
    }
  }

  const showCode = status !== null && status.available && !status.linked && code !== null;
  const actions =
    status === null || !status.available ? null : status.linked ? (
      <button className="btn btn--quiet" onClick={unlink} disabled={busy} aria-busy={busy}>
        {t("waUnlink")}
      </button>
    ) : (
      // "get a code" stays first and in place, so focus keeps meaning what it did
      <>
        <button className={showCode ? "btn btn--quiet" : "btn"} onClick={getCode} disabled={busy} aria-busy={busy}>
          {t("waGetCode")}
        </button>
        {showCode && (
          <button className="btn" onClick={copy} disabled={busy}>
            {t("waCopy")}
          </button>
        )}
      </>
    );

  return (
    <section className="strip" aria-labelledby="wa-title">
      <div className="strip__head">
        <h2 className="strip__title" id="wa-title">{t("waTitle")}</h2>
      </div>
      <div aria-live="polite">
        {showCode && (
          <dl className="batch">
            <div>
              <dt>{t("waCode")}</dt>
              <dd>
                <code>{text}</code>
              </dd>
            </div>
          </dl>
        )}
        {status !== null && (
          <div className="strip__body">
            {!status.available ? (
              <p className="field__hint">{t("waUnavailable")}</p>
            ) : status.linked ? (
              <>
                <p>{t("waLinked", { number: status.number_masked ?? "" })}</p>
                {!status.opted_in && <p className="field__hint">{t("waOptedOut")}</p>}
              </>
            ) : code ? (
              <p>{t("waSendCode", { text, number: code.lab_number, min: Math.round(code.expires_in / 60) })}</p>
            ) : (
              <p className="field__hint">{t("waLede")}</p>
            )}
            {showCode && copied && <p className="field__hint">{t("waCopied")}</p>}
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
