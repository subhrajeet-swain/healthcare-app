import { type FormEvent, useState } from "react";
import { api, messageFor } from "../api";
import { Band } from "../Band";

type Props = { slug: string; onSignedIn: () => void };

export function Login({ slug, onSignedIn }: Props) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }

  function sendCode(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api.requestOtp(slug, phone);
      setStep("code");
    });
  }

  function verify(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api.verify(slug, phone, code);
      onSignedIn();
    });
  }

  const last4 = phone.replace(/\D/g, "").slice(-4);

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>Sign in</h1>
        <p className="lede">
          Use the mobile number you gave your lab.
          <br />
          <span className="hi" lang="hi">लैब को दिया मोबाइल नंबर डालें।</span>
        </p>

        {error && (
          <div className="msg msg--error" role="alert">
            <strong>Problem</strong>
            {error}
          </div>
        )}

        {step === "phone" ? (
          <form onSubmit={sendCode} noValidate>
            <div className="field">
              <label htmlFor="phone">Mobile number</label>
              <div className="phone">
                <span aria-hidden="true">+91</span>
                <input
                  id="phone"
                  className="text"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel-national"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  aria-describedby="phone-hint"
                  required
                />
              </div>
              <span id="phone-hint" className="field__hint">
                10 digits. We send a 6-digit code to this number.
              </span>
            </div>
            <button className="btn btn--block" disabled={busy}>
              {busy ? "Sending…" : "Send code"}
            </button>
          </form>
        ) : (
          <form onSubmit={verify} noValidate>
            <div className="field">
              <label htmlFor="code">6-digit code</label>
              <div className="code">
                <input
                  id="code"
                  className="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  aria-describedby="code-hint"
                  autoFocus
                  required
                />
              </div>
              <span id="code-hint" className="field__hint">
                Sent to the number ending {last4}. It works for 5 minutes.
              </span>
            </div>
            <button className="btn btn--block" disabled={busy || code.length !== 6}>
              {busy ? "Checking…" : "Verify and continue"}
            </button>
            <button type="button" className="linkbtn" onClick={() => { setStep("phone"); setCode(""); }}>
              Change number
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
