import { type FormEvent, useRef, useState } from "react";
import { api, messageFor } from "./api";
import { useLang } from "./i18n";
import { go } from "./routes";

export function Upload() {
  const { lang, t } = useLang();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = input.current?.files?.[0];
    if (!file) {
      setError(t("chooseFirst"));
      input.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.uploadReport(file);
      go(`/reports/${id}`);
    } catch (err) {
      setError(messageFor(err, lang));
      setBusy(false);
    }
  }

  return (
    <form className="strip" aria-labelledby="upload-title" onSubmit={submit}>
      <div className="strip__head">
        <h2 className="strip__title" id="upload-title">
          {t("addReport")}
        </h2>
      </div>
      <div className="strip__body">
        <div className="field">
          <label htmlFor="report-file">
            {t("reportFile")}
          </label>
          <span className="field__hint" id="report-file-hint">
            {t("fileHint")}
          </span>
          <input
            ref={input}
            id="report-file"
            className="file"
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            aria-describedby="report-file-hint"
            disabled={busy}
          />
        </div>
        {error && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {error}
          </div>
        )}
        <button className="btn" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? t("uploading") : t("upload")}
        </button>
      </div>
    </form>
  );
}
