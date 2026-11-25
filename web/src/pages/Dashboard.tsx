import { useEffect, useState } from "react";
import { Account } from "../Account";
import { type Me, type ReportSummary, api } from "../api";
import { Band } from "../Band";
import { type Key, useLang } from "../i18n";
import { type Role, go } from "../routes";
import { Nav } from "../Nav";
import { Upload } from "../Upload";
import { Staff } from "./Staff";
import { STATUS, TRIAGE, shortDate } from "../words";

type Props = { me: Me; onSignOut: () => void; onDeleted: () => void };

const HEAD: Record<Role, [Key, Key]> = {
  patient: ["dashPatient", "emptyPatient"],
  lab_staff: ["dashStaff", "emptyStaff"],
  doctor: ["dashDoctor", "emptyDoctor"],
  lab_admin: ["dashAdmin", "emptyAdmin"],
  platform_admin: ["dashPlatform", "emptyPlatform"],
};

function ReportList() {
  const { lang, t } = useLang();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.reports().then(setReports, () => setFailed(true));
  }, []);

  if (failed) {
    return (
      <div className="msg msg--error" role="alert">
        <strong>{t("problem")}</strong>
        {t("reportsFailed")}
      </div>
    );
  }
  if (reports === null) return <p className="lede">{t("loadingReports")}</p>;
  return (
    <section className="strip" aria-labelledby="reports-title">
      <div className="strip__head">
        <h2 className="strip__title" id="reports-title">{t("reports")}</h2>
      </div>
      {reports.length === 0 ? (
        <div className="strip__body">
          <p>{t("emptyPatient")}</p>
        </div>
      ) : (
        <ul className="perf-list">
          {reports.map((r) => {
            const finished = r.status === "ready" || r.status === "needs_review";
            const href = `/reports/${r.id}`;
            return (
              <li key={r.id} className="report-row">
                <a
                  className="report-row__link"
                  href={href}
                  onClick={(e) => {
                    e.preventDefault();
                    go(href);
                  }}
                >
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
      )}
    </section>
  );
}

export function Dashboard({ me, onSignOut, onDeleted }: Props) {
  const { t } = useLang();
  const patient = me.role === "patient";

  const greeting = me.name ? (
    <>
      {t("greeting")}, <span className="nowrap">{me.name}</span>
    </>
  ) : (
    t("greeting")
  );

  return (
    <div className="shell">
      {/* patients sign out from Profile, so the band stays the same on every tab */}
      <Band line={greeting}>
        {!patient && (
          <button className="btn btn--quiet" onClick={onSignOut}>
            {t("signOut")}
          </button>
        )}
      </Band>
      <main>
        <h1>{t(HEAD[me.role][0])}</h1>

        {patient ? (
          <>
            <Upload />
            <ReportList />
          </>
        ) : me.role === "lab_staff" || me.role === "lab_admin" ? (
          <Staff />
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
