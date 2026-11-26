import type { ReactNode } from "react";
import { type Key, useLang } from "./i18n";
import { go } from "./routes";

export type Tab = "reports" | "trends" | "chat" | "profile";

// ponytail: Family joins in phase 2, no placeholder tab until it exists
const ICONS: Record<Tab, ReactNode> = {
  reports: <><path d="M7 3h7l4 4v14H7z" /><path d="M10 12h5M10 16h5" /></>,
  trends: <><path d="M4 18l5-6 4 3 7-9" /><path d="M15 6h5v5" /></>,
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  profile: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
};

const TABS: [Tab, string, Key][] = [
  ["reports", "/", "navReports"],
  ["trends", "/timeline", "navTrends"],
  ["chat", "/chat", "navChat"],
  ["profile", "/profile", "navProfile"],
];

/** Patient bottom nav: a floating pill, the page you are on filled black. */
export function Nav({ active }: { active: Tab }) {
  const { t } = useLang();
  return (
    <nav className="nav" aria-label={t("navLabel")}>
      <ul className="nav__list">
        {TABS.map(([tab, href, key]) => (
          <li key={tab}>
            <a
              className="nav__item"
              href={href}
              aria-current={tab === active ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                go(href);
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[tab]}</svg>
              {t(key)}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
