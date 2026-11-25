import { useEffect, useRef, useState } from "react";
import { type Me, type ReportSummary, api, messageFor } from "../api";
import { Band } from "../Band";
import { type Key, useLang } from "../i18n";
import { type Role, go } from "../routes";
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

  const greeting = me.name ? (
    <>
      {t("greeting")}, <span className="nowrap">{me.name}</span>
    </>
  ) : (
    t("greeting")
  );

  return (
    <div className="shell">
      <Band line={greeting}>
        <button className="btn btn--quiet" onClick={onSignOut}>
          {t("signOut")}
        </button>
      </Band>
      <main>
        <h1>{t(HEAD[me.role][0])}</h1>

        {me.role === "patient" ? (
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
      </main>
    </div>
  );
}
