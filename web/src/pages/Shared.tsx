import { useCallback, useEffect, useState } from "react";
import { ApiError, type SharedView, api, messageFor } from "../api";
import { Band } from "../Band";
import { useLang } from "../i18n";
import { shortDate, shortDateTime } from "../words";
import { ReportBody } from "./Report";

type Props = { slug: string; token: string };

/** What a doctor opens from a share link: read-only, no sign-in, no nav, nothing to click. */
export function Shared({ slug, token }: Props) {
  const { lang, t } = useLang();
  const [view, setView] = useState<SharedView | null>(null);
  const [state, setState] = useState<"loading" | "gone" | "failed">("loading");
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.shared(slug, token).then(
      (v) => setView(v),
      (e) => {
        setError(e);
        // unknown, wrong, expired and revoked links are one 404, and look the same here
        setState(e instanceof ApiError && e.status === 404 ? "gone" : "failed");
      },
    );
  }, [slug, token]);
  useEffect(load, [load]);

  return (
    <div className="shell">
      <Band />
      <main aria-busy={!view && state === "loading"}>
        {view ? (
          <>
            <h1>{t("sharedTitle")}</h1>
            <p className="lede">{t("sharedBy", { when: shortDateTime(view.expires_at, lang) })}</p>
            {view.reports.length === 0 && <p className="lede">{t("sharedEmpty")}</p>}
            {view.reports.map((r) => (
              <article key={r.id}>
                <p className="report-head__line">
                  {r.collected_on
                    ? t("collected", { date: shortDate(r.collected_on, lang) })
                    : t("added", { date: shortDate(r.created_at, lang) })}
                  {r.source === "lab" && ` · ${t("fromLab")}`}
                </p>
                <ReportBody report={r} shared />
              </article>
            ))}
          </>
        ) : state === "gone" ? (
          <>
            <h1>{t("sharedGone")}</h1>
            <p className="lede">{t("sharedGoneBody")}</p>
          </>
        ) : state === "failed" ? (
          <>
            <div className="msg msg--error" role="alert">
              <strong>{t("problem")}</strong>
              {messageFor(error, lang)}
            </div>
            <button
              className="btn"
              onClick={() => {
                setState("loading");
                load();
              }}
            >
              {t("tryAgain")}
            </button>
          </>
        ) : (
          <p className="lede">{t("loading")}</p>
        )}
      </main>
    </div>
  );
}
