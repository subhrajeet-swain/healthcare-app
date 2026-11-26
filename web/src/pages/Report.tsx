import { useCallback, useEffect, useId, useState } from "react";
import { ApiError, type ReportDetail, type Result, type SharedReport, type Status, TERMINAL, api } from "../api";
import { Band } from "../Band";
import { Chat } from "../Chat";
import { rangePosition } from "../range";
import { go } from "../routes";
import { Nav } from "../Nav";
import { Share } from "../Share";
import { StatusSteps } from "../StatusSteps";
import { isStalled } from "../steps";
import { explanationLines } from "../summary";
import { type T, useLang } from "../i18n";
import { FLAG, NEXT, TRIAGE, fmt, shortDate } from "../words";

type Props = { id: string; nav?: boolean };

const POLL_MS = 5000;

/** Detail plus live status: SSE first, polling if the stream fails. */
function useReport(id: string) {
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState<"missing" | "failed" | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.report(id);
      setReport(r);
      setError(null);
      return r.status;
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "missing" : "failed");
      return null;
    }
  }, [id]);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    let source: EventSource | undefined;

    const poll = async () => {
      const s = await load();
      if (!stopped && (s === null || !TERMINAL.includes(s))) timer = window.setTimeout(poll, POLL_MS);
    };

    load().then((s) => {
      if (stopped || s === null || TERMINAL.includes(s)) return;
      source = new EventSource(api.eventsUrl(id), { withCredentials: true });
      source.addEventListener("status", (ev) => {
        const status = (JSON.parse((ev as MessageEvent).data) as { status: Status }).status;
        // a new step, stamped now, so the stall check sees the pipeline moving
        setReport((r) =>
          r && r.status !== status ? { ...r, status, steps: [...r.steps, { status, at: new Date().toISOString() }] } : r,
        );
        if (TERMINAL.includes(status)) {
          source?.close();
          load(); // results and explanation arrive with the final status
        }
      });
      source.onerror = () => {
        source?.close();
        if (!stopped) poll();
      };
    });

    return () => {
      stopped = true;
      source?.close();
      window.clearTimeout(timer);
    };
  }, [id, load]);

  return { report, error, reload: load };
}

/** Re-render every 15 s while `on`, so time-based copy (the stall note) appears by itself. */
function useNow(on: boolean): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [on]);
  return now;
}

function rangeText(r: Result, t: T): string {
  if (r.ref_low !== null && r.ref_high !== null) return `${fmt(r.ref_low)} – ${fmt(r.ref_high)}`;
  if (r.ref_high !== null) return t("below", { n: fmt(r.ref_high) });
  if (r.ref_low !== null) return t("above", { n: fmt(r.ref_low) });
  return t("notPrinted");
}

export function ResultRow({ r }: { r: Result }) {
  const { lang, t } = useLang();
  const pos = rangePosition(r.value, r.ref_low, r.ref_high);
  return (
    <li className={`result result--${r.triage}`}>
      <div className="result__head">
        <span className="result__name">{r.test_name}</span>
        <span className="result__state">
          {FLAG[r.flag][lang]}
        </span>
      </div>
      <p className="result__value">
        {fmt(r.value)} <span className="result__unit">{r.unit}</span>
      </p>
      {pos.zone && (
        <div className="range" aria-hidden="true">
          <span className="range__zone" style={{ left: `${pos.zone[0]}%`, width: `${pos.zone[1] - pos.zone[0]}%` }} />
          <span className="range__mark" style={{ left: `${pos.pct}%` }} />
        </div>
      )}
      <p className="result__range">{t("normalRange", { range: rangeText(r, t) })}</p>
    </li>
  );
}

type Body = SharedReport & { has_file?: boolean };

/** First on a red report and on the home summary: act today. `phone`, when the lab has one, is a call button. */
export function UrgentBanner({ phone }: { phone?: string | null }) {
  const { t } = useLang();
  return (
    <div className="strip triage triage--red urgent-banner" role="note">
      <p className="next">{t("urgentBanner")}</p>
      {phone && (
        <div className="strip__body">
          <a className="btn" href={`tel:${phone}`}>{phone}</a>
        </div>
      )}
    </div>
  );
}

/** What a finished, visible report says: the verdict, a doctor's note, the results, the explanation.
 * `shared`: a doctor reads it through a link, so the patient-facing "a doctor is checking" line is left out. */
export function ReportBody({ report, shared = false }: { report: Body; shared?: boolean }) {
  const { lang, t } = useLang();
  const banner = report.triage === "red" && !shared;
  const lines = explanationLines(report, lang, banner);
  const RANK = { red: 0, amber: 1, green: 2 } as const;
  const results = [...(report.results ?? [])].sort((a, b) => RANK[a.triage] - RANK[b.triage]);
  const uid = useId(); // several reports on one page (a share link) need their own heading ids
  if (!report.triage) return null;

  return (
    <>
      {banner && <UrgentBanner />}
      <section className={`strip triage triage--${report.triage}`} aria-labelledby={`${uid}-triage`}>
        <div className="strip__head">
          <h2 className="strip__title" id={`${uid}-triage`}>
            {TRIAGE[report.triage][lang]}
          </h2>
        </div>
        {report.next_step && <p className="next">{NEXT[report.next_step][lang]}</p>}
        {!shared && (report.review_pending || (report.status === "needs_review" && !report.doctor_note)) && (
          <div className="strip__body">
            <p>{t(report.review_pending ? "reviewPending" : "doctorTold")}</p>
          </div>
        )}
      </section>

      {report.doctor_note && (
        <section className="strip" aria-labelledby={`${uid}-note`}>
          <div className="strip__head">
            <h2 className="strip__title" id={`${uid}-note`}>
              {t("doctorNote")}
            </h2>
          </div>
          <p className="next" lang={lang}>
            {report.doctor_note.text[lang]}
          </p>
        </section>
      )}

      <section className="tiles" aria-labelledby={`${uid}-results`}>
        <div className="strip__head">
          <h2 className="strip__title" id={`${uid}-results`}>
            {t("results")}
          </h2>
          {report.has_file && (
            <a className="btn btn--quiet btn--small" href={api.fileUrl(report.id)} target="_blank" rel="noopener">
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

      <section className="strip" aria-labelledby={`${uid}-explain`}>
        <div className="strip__head">
          <h2 className="strip__title" id={`${uid}-explain`}>
            {t("whatItSays")}
          </h2>
        </div>
        <ul className="perf-list" lang={lang}>
          {lines.map((s, i) => (
            <li key={i} className={i === 0 && report.urgent && !banner ? "perf-list__urgent" : undefined}>
              {s.text}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export function Report({ id, nav = false }: Props) {
  const { report, error, reload } = useReport(id);
  const now = useNow(!!report && !TERMINAL.includes(report.status));
  const { lang, t } = useLang();

  // with the nav, its Reports tab is the way back
  const back = nav ? undefined : (
    <button className="btn btn--quiet" onClick={() => go("/")}>
      {t("allReports")}
    </button>
  );

  if (error === "missing") {
    return (
      <div className="shell">
        <Band>{back}</Band>
        <main>
          <h1>{t("notFound")}</h1>
          <p className="lede">{t("notFoundBody")}</p>
        </main>
        {nav && <Nav active="reports" />}
      </div>
    );
  }
  if (!report) {
    return (
      <div className="shell">
        <Band>{back}</Band>
        <main aria-busy={!error}>
          {error ? (
            <>
              <div className="msg msg--error" role="alert">
                <strong>{t("problem")}</strong>
                {t("reportFailed")}
              </div>
              <button className="btn" onClick={() => reload()}>
                {t("tryAgain")}
              </button>
            </>
          ) : (
            <p className="lede">{t("loading")}</p>
          )}
        </main>
        {nav && <Nav active="reports" />}
      </div>
    );
  }

  const finished = report.status === "ready" || report.status === "needs_review";

  return (
    <div className="shell">
      <Band />
      <main>
        <h1 className="visually-hidden">{t("yourReport")}</h1>
        <div className="report-head">
          <a className="circle-btn" href="/" aria-label={t("back")} onClick={(e) => { e.preventDefault(); go("/"); }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
          </a>
          <p className="report-head__line">
            {report.collected_on
              ? t("collected", { date: shortDate(report.collected_on, lang) })
              : t("added", { date: shortDate(report.created_at, lang) })}
            {report.source === "lab" && ` · ${t("fromLab")}`}
          </p>
        </div>

        {!finished && (
          <section className="strip" aria-labelledby="progress-title" aria-live="polite">
            <div className="strip__head">
              <h2 className="strip__title" id="progress-title">
                {t("progress")}
              </h2>
            </div>
            {report.status !== "failed" && (
              <div className="strip__body strip__body--first">
                <p className="field__hint">{t(isStalled(report.steps, now) ? "progressSlow" : "progressLede")}</p>
              </div>
            )}
            <StatusSteps report={report} />
            {report.status === "failed" && (
              <div className="strip__body">
                <p>{report.failure_message}</p>
                <button className="btn" onClick={() => go("/")}>
                  {t("uploadAgain")}
                </button>
              </div>
            )}
          </section>
        )}

        {finished && report.triage && (
          <>
            <ReportBody report={report} />
            {nav && <Share reportId={report.id} />}
            <Chat reportId={report.id} />
          </>
        )}
      </main>
      {nav && <Nav active="reports" />}
    </div>
  );
}
