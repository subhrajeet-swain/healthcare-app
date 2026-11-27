import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type Decision,
  type NoteOption,
  type ReviewDetail,
  type ReviewItem,
  api,
  messageFor,
} from "../api";
import { Band } from "../Band";
import { type Key, useLang } from "../i18n";
import { NOTE, NOTE_OPTIONS, dueLabel, reasonTone, reasonWord, testLabel, trendLine } from "../review";
import { go } from "../routes";
import { shortDate } from "../words";
import { ResultRow } from "./Report";

const RANK = { red: 0, amber: 1, green: 2 } as const;
const DECIDED: Record<Exclude<ReviewItem["status"], "pending">, Key> = {
  approved: "docApproved",
  edited: "docEdited",
  escalated: "docEscalated",
};

/** The clock for due labels: re-renders each minute so "due in 5 min" keeps counting down. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function open(href: string) {
  return (e: React.MouseEvent) => {
    e.preventDefault();
    go(href);
  };
}

/** The reason as a pill: its word always, its colour when the reason is clinical. */
function ReasonPill({ item }: { item: ReviewItem }) {
  const { lang } = useLang();
  const tone = reasonTone(item.reason);
  return <span className={`pill pill--${tone ?? "neutral"}`}>{reasonWord(item.reason, lang)}</span>;
}

function Due({ item, now }: { item: ReviewItem; now: Date }) {
  const { lang } = useLang();
  const late = Date.parse(item.due_at) < now.getTime();
  return <span className={`due${late ? " state--red" : ""}`}>{dueLabel(item.due_at, now, lang)}</span>;
}

function Card({ item, now }: { item: ReviewItem; now: Date }) {
  const { lang, t } = useLang();
  const href = `/reviews/${item.id}`;
  const what = item.trend ? `${testLabel(item.trend.test_id)}: ${trendLine(item.trend, lang)}` : item.chat?.question;
  return (
    <li>
      <a className="strip queue-card" href={href} onClick={open(href)}>
        <span className="queue-card__top">
          <span className="queue-card__who">{item.patient_name ?? t("docNoName")}</span>
          <Due item={item} now={now} />
        </span>
        <ReasonPill item={item} />
        {what && <span className="queue-card__what">{what}</span>}
      </a>
    </li>
  );
}

/** The doctor's home: everything that waits for a decision, oldest due first. */
export function Queue() {
  const { t } = useLang();
  const now = useNow();
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    api.doctorQueue().then(
      (list) => {
        setItems(list);
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, []);

  // no polling: every read is audited, so refresh when the doctor comes back to the tab
  useEffect(() => {
    load();
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  if (failed && items === null) {
    return (
      <>
        <div className="msg msg--error" role="alert">
          <strong>{t("problem")}</strong>
          {t("docLoadFailed")}
        </div>
        <button className="btn" onClick={load}>
          {t("tryAgain")}
        </button>
      </>
    );
  }
  if (items === null) return <p className="lede">{t("loading")}</p>;
  if (items.length === 0) {
    return (
      <section className="strip" aria-label={t("dashDoctor")}>
        <div className="strip__body strip__body--first">
          <p>{t("emptyDoctor")}</p>
        </div>
      </section>
    );
  }
  return (
    <>
      <p className="lede">{t("docWaiting", { n: items.length })}</p>
      <ul className="queue">
        {items.map((item) => (
          <Card key={item.id} item={item} now={now} />
        ))}
      </ul>
    </>
  );
}

const CHECK = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7" /></svg>
);

function doneLine(item: ReviewItem): Key {
  if (item.kind === "report" && item.status === "escalated") return "docDoneEscalated";
  if (item.kind === "report") return "docDoneReport";
  if (item.kind === "chat" && item.status === "edited") return "docDoneChat";
  return "docDoneOther";
}

/** Approve, edit (one of four fixed notes) or escalate; once decided, what was decided. */
function Decide({ item, onDecided, onStale }: {
  item: ReviewItem;
  onDecided: (d: ReviewItem["status"], o: NoteOption | null) => void;
  onStale: () => void;
}) {
  const { lang, t } = useLang();
  const [editing, setEditing] = useState(false);
  const [option, setOption] = useState<NoteOption | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const acted = useRef(false);
  const head = useRef<HTMLHeadingElement>(null);

  // after the doctor's own decision, put focus on the result so a screen reader announces it
  useEffect(() => {
    if (acted.current && item.status !== "pending") head.current?.focus();
  }, [item.status]);

  async function act(action: Decision, note: NoteOption | null = null) {
    setBusy(true);
    setError(null);
    try {
      const { status } = await api.decide(item.id, action, note);
      acted.current = true;
      onDecided(status, note);
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.code === "already_decided") onStale(); // show what was decided
    } finally {
      setBusy(false);
    }
  }

  if (item.status !== "pending") {
    return (
      <section className="strip" aria-labelledby="decide-title">
        <div className="strip__head">
          <h2 className="strip__title" id="decide-title" ref={head} tabIndex={-1}>{t("docDecide")}</h2>
          <span className="pill">{t(DECIDED[item.status])}</span>
        </div>
        <div className="strip__body">
          {item.status === "edited" && item.note_option && <p className="note-line">{NOTE[item.note_option][lang]}</p>}
          <p>{t(doneLine(item))}</p>
          <button className="btn btn--block" onClick={() => go("/")}>{t("docBack")}</button>
        </div>
      </section>
    );
  }

  const hint: Key = item.kind === "chat" ? "docHintChat" : item.kind === "trend" ? "docHintTrend" : "docHintReport";
  return (
    <section className="strip" aria-labelledby="decide-title">
      <div className="strip__head">
        <h2 className="strip__title" id="decide-title">{t("docDecide")}</h2>
      </div>
      <div className="strip__body">
        <p className="field__hint">{t(hint)}</p>
        <div className="actions">
          <button className="btn" disabled={busy} onClick={() => act("approve")}>{t("docApprove")}</button>
          <button className="btn btn--quiet" disabled={busy} aria-expanded={editing} aria-controls="note-pick" onClick={() => setEditing((v) => !v)}>
            {t("docEdit")}
          </button>
          {item.kind !== "chat" && (
            <button className="btn btn--quiet" disabled={busy} onClick={() => act("escalate")}>{t("docEscalate")}</button>
          )}
        </div>
      </div>
      {editing && (
        <div className="strip__body" id="note-pick">
          <fieldset className="note-pick" disabled={busy}>
            <legend className="note-pick__legend">{t("docPickNote")}</legend>
            <div className="choices">
              {NOTE_OPTIONS.map((o) => (
                <label key={o} className="choice">
                  <input type="radio" className="visually-hidden" name="note" value={o} checked={option === o} onChange={() => setOption(o)} />
                  <span>
                    {option === o && CHECK}
                    {NOTE[o][lang]}
                  </span>
                </label>
              ))}
            </div>
            <button className="btn btn--block" disabled={busy || !option} aria-busy={busy} onClick={() => option && act("edit", option)}>
              {busy ? t("saving") : t("docSend")}
            </button>
          </fieldset>
        </div>
      )}
      {error !== null && (
        <div className="strip__body">
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {messageFor(error, lang)}
          </div>
        </div>
      )}
    </section>
  );
}

/** One review item: why it waits, the values behind it, and the decision. */
export function Review({ id }: { id: string }) {
  const { lang, t } = useLang();
  const now = useNow();
  const [item, setItem] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState<"missing" | "failed" | null>(null);

  const load = useCallback(() => {
    api.doctorReview(id).then(setItem, (e) => setError(e instanceof ApiError && e.status === 404 ? "missing" : "failed"));
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);
  const retry = () => {
    setError(null);
    load();
  };

  const back = (
    <a className="circle-btn" href="/" aria-label={t("docBack")} onClick={open("/")}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
    </a>
  );

  if (!item) {
    return (
      <div className="shell">
        <Band />
        <main aria-busy={!error}>
          <div className="report-head">{back}</div>
          {error === "missing" ? (
            <h1>{t("docNotFound")}</h1>
          ) : error ? (
            <>
              <div className="msg msg--error" role="alert">
                <strong>{t("problem")}</strong>
                {t("docLoadFailed")}
              </div>
              <button className="btn" onClick={retry}>{t("tryAgain")}</button>
            </>
          ) : (
            <p className="lede">{t("loading")}</p>
          )}
        </main>
      </div>
    );
  }

  const results = [...(item.report?.results ?? [])].sort((a, b) => RANK[a.triage] - RANK[b.triage]);
  const trendName = item.trend && (results.find((r) => r.test_id === item.trend!.test_id)?.test_name ?? testLabel(item.trend.test_id));
  return (
    <div className="shell">
      <Band />
      <main>
        <div className="report-head">
          {back}
          <p className="report-head__line">{t("docRaised", { date: shortDate(item.created_at, lang) })}</p>
        </div>
        <h1 className="review-title">{item.patient_name ?? t("docNoName")}</h1>
        <p className="review-meta">
          <ReasonPill item={item} />
          {item.status === "pending" && <Due item={item} now={now} />}
        </p>

        {item.trend && (
          <section className="strip" aria-labelledby="trend-title">
            <div className="strip__head">
              <h2 className="strip__title" id="trend-title">{trendName}</h2>
            </div>
            <div className="strip__body">
              <p>{trendLine(item.trend, lang)}</p>
            </div>
          </section>
        )}

        {item.chat && (
          <section className="strip" aria-labelledby="held-title">
            <div className="strip__head">
              <h2 className="strip__title" id="held-title">{t("navChat")}</h2>
            </div>
            <ol className="chat">
              {item.chat.question && (
                <li className="chat__msg chat__msg--user">
                  <span className="chat__who">{t("docAsked")}</span>
                  <p>{item.chat.question}</p>
                </li>
              )}
              {item.chat.reply && (
                <li className="chat__msg chat__msg--assistant">
                  <span className="chat__who">{t("docHeld")}</span>
                  <p>{item.chat.reply}</p>
                </li>
              )}
            </ol>
          </section>
        )}

        {item.report ? (
          <section className="tiles" aria-labelledby="values-title">
            <div className="strip__head">
              <h2 className="strip__title" id="values-title">{t("results")}</h2>
              {item.report.has_file && (
                <a className="btn btn--quiet btn--small" href={api.fileUrl(item.report.id)} target="_blank" rel="noopener">
                  {t("viewOriginal")}
                </a>
              )}
            </div>
            <ul className="results">
              {results.map((r) => (
                <ResultRow key={r.test_id} r={r} />
              ))}
            </ul>
          </section>
        ) : (
          <p className="lede">{t("docNoReport")}</p>
        )}

        <Decide
          item={item}
          onDecided={(status, note) => setItem((i) => i && { ...i, status, note_option: note })}
          onStale={load}
        />
      </main>
    </div>
  );
}
