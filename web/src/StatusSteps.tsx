import type { ReportDetail, Status } from "./api";
import { useLang } from "./i18n";
import { STATUS } from "./words";

const PATIENT: Status[] = ["received", "extracting", "explaining", "ready"];
const LAB: Status[] = ["sample_collected", "in_lab", ...PATIENT];

type Props = { report: Pick<ReportDetail, "status" | "source"> };

/** A step list, not a map: each step says Done, Now or Next in words. */
export function StatusSteps({ report }: Props) {
  const { lang, t } = useLang();
  const steps = report.source === "lab" ? LAB : PATIENT;
  const at = report.status === "needs_review" || report.status === "failed" ? "ready" : report.status;
  const current = steps.indexOf(at);
  const done = report.status === "ready" || report.status === "needs_review";

  return (
    <ol className="steps" aria-label={t("progressLabel")}>
      {steps.map((s, i) => {
        const state = i < current || (done && i === current) ? "done" : i === current ? "now" : "next";
        const label = s === "ready" && report.status === "failed" ? STATUS.failed : STATUS[s];
        return (
          <li key={s} className={`steps__item steps__item--${state}`} aria-current={state === "now" ? "step" : undefined}>
            <span className="steps__word">{t(state === "done" ? "stepDone" : state === "now" ? "stepNow" : "stepNext")}</span>
            <span>{label[lang]}</span>
          </li>
        );
      })}
    </ol>
  );
}
