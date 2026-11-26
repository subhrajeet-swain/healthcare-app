import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type StaffReport, api, messageFor } from "../api";
import { useLang } from "../i18n";
import { staffActions } from "../staffActions";
import { STATUS, TRIAGE, shortDate } from "../words";

function Row({ r, onChange, onError }: { r: StaffReport; onChange: () => void; onError: (e: unknown) => void }) {
  const { lang, t } = useLang();
  const [busy, setBusy] = useState(false);
  const can = staffActions(r.status);
  const finished = r.status === "ready" || r.status === "needs_review";

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChange();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="staff-row">
      <div className="staff-row__head">
        <span>
          <span className="report-row__what">{r.name ?? r.phone_masked}</span>
          {r.name && r.phone_masked && `${r.phone_masked} · `}
          {shortDate(r.created_at, lang)}
        </span>
        <span className={`report-row__state${finished && r.triage ? ` state--${r.triage}` : ""}`}>
          {finished && r.triage ? TRIAGE[r.triage][lang] : STATUS[r.status][lang]}
        </span>
      </div>
      {(can.markInLab || can.upload) && (
        <div className="actions">
          {can.markInLab && (
            <button className="btn btn--quiet" disabled={busy} onClick={() => act(() => api.markInLab(r.id))}>
              {t("markInLab")}
            </button>
          )}
          {can.upload && (
            <label className={`btn${busy ? " btn--disabled" : ""}`}>
              {t("uploadResult")}
              <input
                type="file"
                className="visually-hidden"
                accept="application/pdf,image/jpeg,image/png"
                disabled={busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) act(() => api.staffUpload(r.id, f));
                }}
              />
            </label>
          )}
        </div>
      )}
    </li>
  );
}

/** Lab console: order a test for a patient, move it to the lab, upload the result. */
export function Staff() {
  const { lang, t } = useLang();
  const [reports, setReports] = useState<StaffReport[] | null>(null);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState(false);

  const load = useCallback(() => api.staffReports().then(setReports, setError), []);
  useEffect(() => {
    load();
  }, [load]);

  async function order(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCreated(false);
    try {
      await api.order(phone, name);
      setPhone("");
      setName("");
      setCreated(true);
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="strip" aria-labelledby="order-title" onSubmit={order}>
        <div className="strip__head">
          <h2 className="strip__title" id="order-title">
            {t("newOrder")}
          </h2>
        </div>
        <div className="strip__body">
          <div className="field">
            <label htmlFor="order-phone">{t("patientPhone")}</label>
            <div className="phone">
              <span aria-hidden="true">+91</span>
              <input id="order-phone" className="text" type="tel" inputMode="numeric" value={phone} onChange={(e) => setPhone(e.target.value)} required />
            </div>
          </div>
          <div className="field">
            <label htmlFor="order-name">{t("patientName")}</label>
            <input id="order-name" className="text text--boxed" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          {error !== null && (
            <div className="msg msg--error" role="alert">
              <strong>{t("problem")}</strong>
              {messageFor(error, lang)}
            </div>
          )}
          {created && (
            <div className="msg msg--info" role="status">
              {t("orderCreated")}
            </div>
          )}
          <button className="btn" type="submit" disabled={busy} aria-busy={busy}>
            {busy ? t("creating") : t("createOrder")}
          </button>
        </div>
      </form>

      <section className="strip" aria-labelledby="lab-reports-title">
        <div className="strip__head">
          <h2 className="strip__title" id="lab-reports-title">
            {t("labReports")}
          </h2>
        </div>
        {reports === null ? (
          <div className="strip__body">
            <p>{t("loading")}</p>
          </div>
        ) : reports.length === 0 ? (
          <div className="strip__body">
            <p>{t("noLabReports")}</p>
          </div>
        ) : (
          <ul className="perf-list">
            {reports.map((r) => (
              <Row key={r.id} r={r} onChange={load} onError={setError} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
