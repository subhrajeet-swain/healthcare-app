import { type FormEvent, useEffect, useRef, useState } from "react";
import { type ChatMessage, api, messageFor } from "./api";
import { useLang } from "./i18n";

const MAX = 500;

export function Chat({ reportId }: { reportId: string }) {
  const { lang, t } = useLang();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.chatHistory(reportId).then(setMessages, () => undefined);
  }, [reportId]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) {
      input.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { reply, tier } = await api.ask(reportId, q, lang);
      const at = new Date().toISOString();
      setMessages((m) => [...m, { role: "user", text: q, tier, created_at: at }, { role: "assistant", text: reply, tier, created_at: at }]);
      setQuestion("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  return (
    <section className="strip" aria-labelledby="chat-title">
      <div className="strip__head">
        <h2 className="strip__title" id="chat-title">
          {t("askTitle")}
        </h2>
      </div>
      <div className="strip__body">
        <p className="field__hint">{t("askHint")}</p>
      </div>
      {messages.length > 0 ? (
        <ol className="chat" aria-live="polite">
          {messages.map((m, i) => (
            <li key={i} className={`chat__msg chat__msg--${m.role}`}>
              <span className="chat__who">{t(m.role === "user" ? "you" : "assistant")}</span>
              {m.channel === "whatsapp" && <span className="chat__via">{t("viaWhatsApp")}</span>}
              <p>{m.text}</p>
            </li>
          ))}
        </ol>
      ) : (
        <div className="strip__body">
          <p className="field__hint">{t("noQuestions")}</p>
        </div>
      )}
      <form className="strip__body" onSubmit={send}>
        <div className="field">
          <label htmlFor="question">{t("yourQuestion")}</label>
          <textarea
            ref={input}
            id="question"
            className="textarea"
            rows={2}
            maxLength={MAX}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-describedby="question-left"
            disabled={busy}
          />
          <span id="question-left" className="field__hint" aria-live="polite">
            {t("charsLeft", { n: MAX - question.length })}
          </span>
        </div>
        {error !== null && (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {messageFor(error, lang)}
          </div>
        )}
        <button className="btn" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? t("asking") : t("ask")}
        </button>
      </form>
    </section>
  );
}
