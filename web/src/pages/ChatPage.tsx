import { useEffect, useState } from "react";
import { type ReportSummary, api } from "../api";
import { Band } from "../Band";
import { Chat } from "../Chat";
import { useLang } from "../i18n";
import { Nav } from "../Nav";
import { go, latestReady } from "../routes";
import { shortDate } from "../words";

/** The Chat tab: questions about the newest report that is ready to talk about. */
export function ChatPage() {
  const { lang, t } = useLang();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.reports().then(setReports, () => setFailed(true));
  }, []);

  const report = reports && latestReady(reports);
  const href = report ? `/reports/${report.id}` : "/";

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>{t("navChat")}</h1>
        {failed ? (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {t("reportsFailed")}
          </div>
        ) : reports === null ? (
          <p className="lede">{t("loadingReports")}</p>
        ) : report ? (
          <>
            <p className="lede">
              {t("chatAbout", { date: shortDate(report.collected_on ?? report.created_at, lang) })}{" "}
              <a
                href={href}
                onClick={(e) => {
                  e.preventDefault();
                  go(href);
                }}
              >
                {t("openReport")}
              </a>
            </p>
            <Chat reportId={report.id} />
          </>
        ) : (
          <section className="strip" aria-label={t("navChat")}>
            <div className="strip__body strip__body--first">
              <p>{t("chatNone")}</p>
            </div>
          </section>
        )}
      </main>
      <Nav active="chat" />
    </div>
  );
}
