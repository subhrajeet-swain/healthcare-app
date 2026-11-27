import type React from "react";
import { useEffect, useState } from "react";
import { Account } from "../Account";
import { type Me, type ReportDetail, type ReportSummary, type Triage, api } from "../api";
import { Band } from "../Band";
import { type Key, useLang } from "../i18n";
import { type Role, go } from "../routes";
import { Nav } from "../Nav";
import { stateCounts, summarize } from "../summary";
import { Upload } from "../Upload";
import { Queue } from "./Doctor";
import { UrgentBanner } from "./Report";
import { Staff } from "./Staff";
import { NEXT, STATUS, TRIAGE, shortDate } from "../words";

type Props = { me: Me; onSignOut: () => void; onDeleted: () => void };

const HEAD: Record<Role, [Key, Key]> = {
  patient: ["dashPatient", "emptyPatient"],
  lab_staff: ["dashStaff", "emptyStaff"],
  doctor: ["dashDoctor", "emptyDoctor"],
  lab_admin: ["dashAdmin", "emptyAdmin"],
  platform_admin: ["dashPlatform", "emptyPlatform"],
};

const COUNT: Record<Triage, Key> = { green: "countGreen", amber: "countAmber", red: "countRed" };

const ARROW = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
);

function open(href: string) {
  return (e: React.MouseEvent) => {
    e.preventDefault();
    go(href);
  };
}

/** Patient home: how the latest report went in one number, then every report. */
function PatientHome() {
  const { lang, t } = useLang();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [detail, setDetail] = useState<ReportDetail | null>(null);

  useEffect(() => {
    api.reports().then(setReports, () => setFailed(true));
  }, []);

  // the latest report's next step and per-state counts live on its detail; the card works without it
  const latestId = reports?.[0]?.id;
  useEffect(() => {
    if (latestId) api.report(latestId).then(setDetail, () => undefined);
  }, [latestId]);

  if (failed) {
    return (
      <div className="msg msg--error" role="alert">
        <strong>{t("problem")}</strong>
        {t("reportsFailed")}
      </div>
    );
  }
  if (reports === null) return <p className="lede">{t("loadingReports")}</p>;
  if (reports.length === 0) {
    return (
      <>
        <Upload />
        <section className="strip" aria-label={t("reports")}>
          <div className="strip__body strip__body--first">
            <p>{t("emptyPatient")}</p>
          </div>
        </section>
      </>
    );
  }

  const s = summarize(reports);
  const latest = s.latest!;
  const latestRead = (latest.status === "ready" || latest.status === "needs_review") && s.latestTests > 0;
  const latestHref = `/reports/${latest.id}`;
  const fresh = detail?.id === latest.id ? detail : null;
  const counts = stateCounts(fresh?.results ?? []);
  const next = fresh?.next_step;
  return (
    <>
      {latest.triage === "red" && <UrgentBanner phone={fresh?.lab_phone} />}
      <section className="strip summary" aria-labelledby="summary-title">
        <h2 className="summary__number" id="summary-title">
          {latestRead
            ? s.latestTests === 1 ? t("testsOne") : t("testsMany", { n: s.latestTests })
            : STATUS[latest.status][lang]}
        </h2>
        <span className="summary__label">
          {t("latestReport", { date: shortDate(latest.collected_on ?? latest.created_at, lang) })}
        </span>
        {latestRead && (
          <div className="summary__pills">
            {counts.length > 0
              ? counts.map(([state, n]) => (
                  <span key={state} className={`pill pill--${state}`}>{t(COUNT[state], { n })}</span>
                ))
              : latest.triage && <span className={`pill pill--${latest.triage}`}>{TRIAGE[latest.triage][lang]}</span>}
          </div>
        )}
        {latestRead && next && next !== "no_action" && <p className="summary__next">{NEXT[next][lang]}</p>}
        <a className="btn btn--block" href={latestHref} onClick={open(latestHref)}>
          {t("openReport")}
          {ARROW}
        </a>
      </section>

      <div className="stats">
        <div className="stat"><span className="stat__n">{s.reports}</span><span className="stat__label">{t("statReports")}</span></div>
        <div className="stat"><span className="stat__n">{s.testsRead}</span><span className="stat__label">{t("statTests")}</span></div>
        <div className="stat"><span className={`stat__n${s.urgent ? " state--red" : ""}`}>{s.urgent}</span><span className="stat__label">{t("statUrgent")}</span></div>
      </div>

      <section className="strip" aria-labelledby="reports-title">
        <div className="strip__head">
          <h2 className="strip__title" id="reports-title">{t("reports")}</h2>
        </div>
        <ul className="perf-list">
          {reports.map((r) => {
            const finished = r.status === "ready" || r.status === "needs_review";
            const href = `/reports/${r.id}`;
            return (
              <li key={r.id} className="report-row">
                <a className="report-row__link" href={href} onClick={open(href)}>
                  <span className="report-row__date">
                    {r.tests && <span className="report-row__what">{r.tests}</span>}
                    {shortDate(r.collected_on ?? r.created_at, lang)}
                    {r.source === "lab" && ` · ${t("fromLab")}`}
                  </span>
                  <span className={`report-row__state${finished && r.triage ? ` state--${r.triage}` : ""}`}>
                    {finished && r.triage ? TRIAGE[r.triage][lang] : STATUS[r.status][lang]}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      </section>

      <Upload />
    </>
  );
}

export function Dashboard({ me, onSignOut, onDeleted }: Props) {
  const { t } = useLang();
  const patient = me.role === "patient";

  const greeting = (
    <>
      <span className="band__hello">{t("greeting")}</span>
      {me.name && <span className="band__person">{me.name}</span>}
    </>
  );

  return (
    <div className="shell">
      {/* patients sign out from Profile, so the band stays the same on every tab */}
      <Band line={greeting} initial={me.name?.trim().charAt(0).toUpperCase()}>
        {!patient && (
          <button className="btn btn--quiet" onClick={onSignOut}>
            {t("signOut")}
          </button>
        )}
      </Band>
      <main>
        <h1 className={patient ? "visually-hidden" : undefined}>{t(HEAD[me.role][0])}</h1>

        {patient ? (
          <PatientHome />
        ) : me.role === "lab_staff" || me.role === "lab_admin" ? (
          <Staff />
        ) : me.role === "doctor" ? (
          <Queue />
        ) : (
          <section className="strip" aria-label="Status">
            <div className="strip__body strip__body--first">
              <p>{t(HEAD[me.role][1])}</p>
            </div>
          </section>
        )}

        {/* patients find their account under Profile in the nav */}
        {!patient && <Account me={me} onDeleted={onDeleted} />}
      </main>
      {patient && <Nav active="reports" />}
    </div>
  );
}
