import { type FormEvent, useState } from "react";
import { api, messageFor } from "../api";
import { Band } from "../Band";
import { useLang } from "../i18n";

type Props = { slug: string; onSignedIn: () => Promise<void> };

export function Login({ slug, onSignedIn }: Props) {
  const { lang, t } = useLang();
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
      setError(messageFor(e, lang));
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
    if (code.length !== 6) {
      setError(t("needSixDigits"));
      return;
    }
    run(async () => {
      await api.verify(slug, phone, code);
      await onSignedIn();
    });
  }

  const last4 = phone.replace(/\D/g, "").slice(-4);

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>{t("signIn")}</h1>
        <p className="lede">{t(step === "phone" ? "ledePhone" : "ledeCode")}</p>

        {error && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {error}
          </div>
        )}

        {step === "phone" ? (
          <form onSubmit={sendCode} noValidate>
            <div className="field">
              <label htmlFor="phone">{t("mobileNumber")}</label>
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
                {t("phoneHint")}
              </span>
            </div>
            <button className="btn btn--block" disabled={busy} aria-busy={busy}>
              {busy ? t("sending") : t("sendCode")}
            </button>
          </form>
        ) : (
          <form onSubmit={verify} noValidate>
            <div className="field">
              <label htmlFor="code">{t("codeLabel")}</label>
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
                {t("codeHint", { last4 })}
              </span>
            </div>
            <button className="btn btn--block" disabled={busy} aria-busy={busy}>
              {busy ? t("checking") : t("verify")}
            </button>
            <button type="button" className="linkbtn" onClick={() => { setStep("phone"); setCode(""); }}>
              {t("changeNumber")}
            </button>
          </form>
        )}
      </main>
    </div>
  );
}
