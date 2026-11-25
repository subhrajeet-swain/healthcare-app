import type { ReportDetail } from "./api";
import { type Key, useLang } from "./i18n";
import { type StepState, stepStates } from "./steps";
import { STATUS } from "./words";

const WORD: Record<StepState, Key> = { done: "stepDone", now: "stepNow", later: "stepLater", stopped: "stepStopped" };

type Props = { report: Pick<ReportDetail, "status" | "source"> };

/** A step list, not a map: each step says Done, Now, Later or Stopped in words. */
export function StatusSteps({ report }: Props) {
  const { lang, t } = useLang();
  return (
    <ol className="steps" aria-label={t("progressLabel")}>
      {stepStates(report.status, report.source).map(([s, state]) => (
        <li key={s} className={`steps__item steps__item--${state}`} aria-current={state === "now" ? "step" : undefined}>
          <span className="steps__word">{t(WORD[state])}</span>
          <span>{STATUS[s][lang]}</span>
        </li>
      ))}
    </ol>
  );
}
