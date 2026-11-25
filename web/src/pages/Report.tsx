import { useCallback, useEffect, useState } from "react";
import { ApiError, type ReportDetail, type Result, type Status, TERMINAL, api } from "../api";
import { Band } from "../Band";
import { Chat } from "../Chat";
import { rangePosition } from "../range";
import { go } from "../routes";
import { StatusSteps } from "../StatusSteps";
import { type T, useLang } from "../i18n";
import { FLAG, NEXT, TRIAGE, shortDate } from "../words";

type Props = { id: string };

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
        setReport((r) => (r ? { ...r, status } : r));
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

function rangeText(r: Result, t: T): string {
  if (r.ref_low !== null && r.ref_high !== null) return `${r.ref_low} – ${r.ref_high}`;
  if (r.ref_high !== null) return t("below", { n: r.ref_high });
  if (r.ref_low !== null) return t("above", { n: r.ref_low });
  return t("notPrinted");
}

function ResultRow({ r }: { r: Result }) {
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
        {r.value} <span className="result__unit">{r.unit}</span>
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

export function Report({ id }: Props) {
  const { report, error, reload } = useReport(id);
  const { lang, t } = useLang();

  const back = (
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
      </div>
    );
  }

  const finished = report.status === "ready" || report.status === "needs_review";
  const explanation = report.explanations[lang] ?? report.explanations.en;
  // the closing advice is the NEXT tag above; don't print it twice
  const lines = (explanation?.statements ?? []).filter(
    (s, i, all) => !(report.next_step !== "no_action" && s.source === "system" && i === all.length - 1 && i > 0),
  );
  const RANK = { red: 0, amber: 1, green: 2 } as const;
  const results = [...report.results].sort((a, b) => RANK[a.triage] - RANK[b.triage]);

  return (
    <div className="shell">
      <Band>{back}</Band>
      <main>
        <h1>{t("yourReport")}</h1>
        <p className="lede">
          {report.collected_on
            ? t("collected", { date: shortDate(report.collected_on, lang) })
            : t("added", { date: shortDate(report.created_at, lang) })}
          {report.source === "lab" && ` · ${t("fromLab")}`}
        </p>

        {!finished && (
          <section className="strip" aria-labelledby="progress-title" aria-live="polite">
            <div className="strip__head">
              <h2 className="strip__title" id="progress-title">
                {t("progress")}
              </h2>
            </div>
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
            <section className={`strip triage triage--${report.triage}`} aria-labelledby="triage-title">
              <div className="strip__head">
                <h2 className="strip__title" id="triage-title">
                  {TRIAGE[report.triage][lang]}
                </h2>
              </div>
              {report.status === "needs_review" && (
                <div className="strip__body">
                  <p>{t("doctorTold")}</p>
                </div>
              )}
              {report.next_step && (
                <p className="next">
                  <span className="next__tag">{t("next")}</span>
                  {NEXT[report.next_step][lang]}
                </p>
              )}
            </section>

            <section className="strip" aria-labelledby="explain-title">
              <div className="strip__head">
                <h2 className="strip__title" id="explain-title">
                  {t("whatItSays")}
                </h2>
              </div>
              <ul className="perf-list" lang={lang}>
                {lines.map((s, i) => (
                  <li key={i} className={i === 0 && report.urgent ? "perf-list__urgent" : undefined}>
                    {s.text}
                  </li>
                ))}
              </ul>
            </section>

            <section className="strip" aria-labelledby="results-title">
              <div className="strip__head">
                <h2 className="strip__title" id="results-title">
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

            <Chat reportId={report.id} />
          </>
        )}
      </main>
    </div>
  );
}
