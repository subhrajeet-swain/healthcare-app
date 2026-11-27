import { useEffect, useState } from "react";
import { type TimelineTest, api } from "../api";
import { Band } from "../Band";
import { PAD, scale, shown } from "../chart";
import { type T, useLang } from "../i18n";
import { Nav } from "../Nav";
import { shortDate } from "../words";

const W = 320; // the chart's own units: the SVG scales to its card, never past 30rem
const H = 190;
const CHAR = 8.5; // tick label width per character at 14px, for the left margin

function rangeText(p: TimelineTest["points"][number], unit: string, t: T): string | null {
  if (p.ref_low !== null && p.ref_high !== null) return `${shown(p.ref_low)} – ${shown(p.ref_high)} ${unit}`;
  if (p.ref_high !== null) return t("below", { n: `${shown(p.ref_high)} ${unit}` });
  if (p.ref_low !== null) return t("above", { n: `${shown(p.ref_low)} ${unit}` });
  return null;
}

/** One test as a line over time. The band is the latest report's normal range; the last value is written on the chart. */
function Chart({ test }: { test: TimelineTest }) {
  const { lang, t } = useLang();
  const { points, unit } = test;
  const plain = scale(points, W, H);
  const labels = plain.yTicks.map(shown);
  const padL = Math.max(PAD.l, Math.ceil(Math.max(...labels.map((l) => l.length)) * CHAR) + 12);
  const { dots, band, tickY } = padL === PAD.l ? plain : scale(points, W, H, padL);
  const last = dots[dots.length - 1];
  const prev = dots[dots.length - 2];
  const lastValue = points[points.length - 1];
  const lonely = dots.length === 1;
  const sameDay = points[0].observed_on === lastValue.observed_on;
  const right = W - PAD.r;
  // The last value's label sits above its dot; a line coming down into the dot runs through that
  // spot, so the label goes under it, unless the dot is too low for room.
  const under = prev !== undefined && prev.y < last.y && last.y + 30 < H - PAD.b;
  const range = rangeText(lastValue, unit, t);
  const when = (iso: string) => shortDate(iso, lang);

  return (
    <>
      <svg className="chart__svg" viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
        {band && <rect className="chart__band" x={padL} y={band.y} width={right - padL} height={Math.max(band.h, 1)} rx="4" />}
        {tickY.map((y, i) => (
          <g key={y}>
            <line className="chart__grid" x1={padL} x2={right} y1={y} y2={y} />
            <text className="chart__tick" x={padL - 8} y={y} dy="0.35em" textAnchor="end">{labels[i]}</text>
          </g>
        ))}
        {!lonely && <polyline className="chart__line" pathLength="1" points={dots.map((d) => `${d.x},${d.y}`).join(" ")} />}
        {dots.map((d, i) => (
          <circle key={points[i].report_id} className={i === dots.length - 1 ? "chart__dot chart__dot--last" : "chart__dot"}
            cx={d.x} cy={d.y} r={i === dots.length - 1 ? 7 : 5}>
            <title>{`${when(points[i].observed_on)}: ${shown(points[i].value)} ${unit}`}</title>
          </circle>
        ))}
        <text className="chart__last" x={last.x} y={under ? last.y + 28 : last.y - 14} textAnchor={lonely ? "middle" : "end"}>
          {shown(lastValue.value)}
          <tspan className="chart__unit" dx="4">{unit}</tspan>
        </text>
        {sameDay ? (
          <text className="chart__date" x={(padL + right) / 2} y={H - 8} textAnchor="middle">{when(lastValue.observed_on)}</text>
        ) : (
          <>
            <text className="chart__date" x={padL} y={H - 8}>{when(points[0].observed_on)}</text>
            <text className="chart__date" x={right} y={H - 8} textAnchor="end">{when(lastValue.observed_on)}</text>
          </>
        )}
      </svg>
      {/* the picture for screen readers is the same series, as text */}
      <ul className="visually-hidden" aria-label={t("chartSeries")}>
        {points.map((p) => (
          <li key={p.report_id}>{`${when(p.observed_on)}: ${shown(p.value)} ${unit}`}</li>
        ))}
      </ul>
      {range && (
        <p className="chart__legend">
          <span className="chart__swatch" aria-hidden="true" />
          {t("normalRange", { range })}
        </p>
      )}
    </>
  );
}

function TestCard({ test }: { test: TimelineTest }) {
  const { t } = useLang();
  const { trend, excluded } = test;
  const units = [...new Set(excluded.map((e) => e.unit))].join(", ");
  return (
    <section className="strip" aria-labelledby={`t-${test.test_id}`}>
      <div className="strip__head">
        <h2 className="strip__title" id={`t-${test.test_id}`}>{test.test_name}</h2>
      </div>
      <div className="chart">
        {trend && (
          <div className="chart__pills">
            <span className="pill pill--amber">{t(trend.direction === "rising" ? "trendRising" : "trendFalling")}</span>
            {trend.review_status === "pending" && <span className="pill">{t("trendInReview")}</span>}
          </div>
        )}
        <Chart test={test} />
        {excluded.length > 0 && (
          <p className="chart__note">
            {excluded.length === 1 ? t("excludedOne", { units }) : t("excludedMany", { n: excluded.length, units })}
          </p>
        )}
      </div>
    </section>
  );
}

/** The Trends tab: every test the patient has more than a note about, one chart each. */
export function Timeline() {
  const { t } = useLang();
  const [tests, setTests] = useState<TimelineTest[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.timeline().then(setTests, () => setFailed(true));
  }, []);

  return (
    <div className="shell">
      <Band />
      <main>
        <h1>{t("navTrends")}</h1>
        {failed ? (
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {t("trendsFailed")}
          </div>
        ) : tests === null ? (
          <p className="lede">{t("loadingTrends")}</p>
        ) : tests.length === 0 ? (
          <section className="strip" aria-label={t("navTrends")}>
            <div className="strip__body strip__body--first">
              <p>{t("trendsEmpty")}</p>
            </div>
          </section>
        ) : (
          <>
            <p className="lede">{t("trendsLede")}</p>
            {tests.map((test) => (
              <TestCard key={test.test_id} test={test} />
            ))}
          </>
        )}
      </main>
      <Nav active="trends" />
    </div>
  );
}
