import { useState } from "react";
import { type Me, api, messageFor } from "../api";
import { Band } from "../Band";
import { type Role, dashboardFor } from "../routes";

type Props = { me: Me; onSignOut: () => void; onDeleted: () => void };

const EMPTY: Record<Role, string> = {
  patient: "No reports yet. When your lab adds a report, it appears here with a plain-language explanation and your next step.",
  lab_staff: "Report uploads arrive in a later release. Nothing to do here yet.",
  doctor: "Nothing to review. Red results and trend alerts will wait here for your sign-off.",
  lab_admin: "Lab settings arrive in a later release.",
  platform_admin: "Platform tools arrive in a later release.",
};

export function Dashboard({ me, onSignOut, onDeleted }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function deleteAll() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteMe();
      onDeleted();
    } catch (e) {
      setError(messageFor(e));
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <Band>
        <button className="btn btn--quiet" onClick={onSignOut}>
          Sign out
        </button>
      </Band>
      <main>
        <p className="lede">
          {me.name ? `Namaste, ${me.name}` : "Namaste"} · <span className="hi" lang="hi">नमस्ते</span>
        </p>
        <h1>{dashboardFor(me.role)}</h1>

        <section className="strip" aria-label="Status">
          <div className="strip__body" style={{ borderTop: 0 }}>
            <p>{EMPTY[me.role]}</p>
          </div>
        </section>

        <section className="strip" aria-labelledby="account-title">
          <div className="strip__head">
            <h2 className="strip__title" id="account-title">Your account</h2>
          </div>
          <dl className="batch">
            <div>
              <dt>Phone</dt>
              <dd>{me.phone_masked}</dd>
            </div>
            <div>
              <dt>Consent</dt>
              <dd>{me.consent.core ? "Given" : "Not given"}</dd>
            </div>
          </dl>
          <div className="strip__body">
            {error && (
              <div className="msg msg--error" role="alert">
                <strong>Problem</strong>
                {error}
              </div>
            )}
            {confirming ? (
              <div role="group" aria-labelledby="delete-q">
                <p id="delete-q">
                  <strong>Delete everything?</strong> Your account, consents and sign-in are removed. This cannot be undone.
                </p>
                <div className="actions">
                  <button className="btn btn--danger" onClick={deleteAll} disabled={busy}>
                    {busy ? "Deleting…" : "Yes, delete my data"}
                  </button>
                  <button className="btn btn--quiet" onClick={() => setConfirming(false)} disabled={busy}>
                    Keep my data
                  </button>
                </div>
              </div>
            ) : (
              <div className="actions">
                <a className="btn btn--quiet" href={api.exportUrl} download>
                  Download my data
                </a>
                <button className="btn btn--quiet" onClick={() => setConfirming(true)}>
                  Delete my data
                </button>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
