import { useCallback, useEffect, useRef, useState } from "react";
import { type ShareLink, api, messageFor } from "./api";
import { type Key, useLang } from "./i18n";
import { shortDateTime } from "./words";

const HOURS: [number, Key][] = [
  [1, "shareH1"],
  [24, "shareH24"],
  [168, "shareD7"],
];

/** Report page: make a time-limited, read-only link for a doctor, copy it, and stop it again. */
export function Share({ reportId }: { reportId: string }) {
  const { lang, t } = useLang();
  const [hours, setHours] = useState(24);
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [made, setMade] = useState<{ url: string; expires_at: string } | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);

  const reload = useCallback(() => api.shares().then(setLinks, () => undefined), []);
  useEffect(() => {
    reload();
  }, [reload]);

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false); // no clipboard (an insecure page): leave the link selected to copy by hand
      field.current?.select();
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(messageFor(e, lang));
    } finally {
      setBusy(false);
    }
  }

  const create = () =>
    act(async () => {
      setCopied(null);
      const link = await api.share([reportId], hours);
      setMade(link);
      await copy(link.url);
    });

  const open = links.filter((l) => l.report_ids.includes(reportId));

  return (
    <section className="strip" aria-labelledby="share-title">
      <div className="strip__head">
        <h2 className="strip__title" id="share-title">
          {t("shareTitle")}
        </h2>
      </div>
      <div className="strip__body">
        <p>{t("shareLede")}</p>
        <div className="field">
          <span id="share-for" className="family__label">
            {t("shareFor")}
          </span>
          <div className="toggle toggle--flat toggle--three" role="group" aria-labelledby="share-for">
            {HOURS.map(([h, key]) => (
              <button key={h} type="button" className="toggle__btn" aria-pressed={hours === h} onClick={() => setHours(h)}>
                {t(key)}
              </button>
            ))}
          </div>
        </div>
        {error && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {error}
          </div>
        )}
        <button className="btn" onClick={create} disabled={busy} aria-busy={busy}>
          {busy ? t("shareMaking") : t("shareMake")}
        </button>
      </div>

      {made && (
        <div className="strip__body">
          <div className="field">
            <label htmlFor="share-url">{t("shareLink")}</label>
            <input
              id="share-url"
              ref={field}
              className="text text--boxed"
              readOnly
              value={made.url}
              onFocus={(e) => e.currentTarget.select()}
            />
          </div>
          <div className="actions">
            <button className="btn btn--quiet btn--small" onClick={() => copy(made.url)}>
              {t("shareCopy")}
            </button>
          </div>
          <p className="field__hint" role="status">
            {copied === true && `${t("shareCopied")} `}
            {copied === false && `${t("shareSelect")} `}
            {t("shareExpires", { when: shortDateTime(made.expires_at, lang) })}
          </p>
        </div>
      )}

      {open.length > 0 && (
        <div className="strip__body">
          <h3 className="family__sub">{t("shareOpen")}</h3>
          <ul className="perf-list">
            {open.map((l) => (
              <li key={l.id} className="staff-row">
                <div className="staff-row__head">
                  <span>{t("shareExpires", { when: shortDateTime(l.expires_at, lang) })}</span>
                  <button className="btn btn--quiet btn--small" disabled={busy} onClick={() => act(() => api.unshare(l.id))}>
                    {t("shareStop")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
