import { type Key, useLang } from "./i18n";
import { go } from "./routes";

export type Tab = "reports" | "chat" | "profile";

// ponytail: Family joins in phase 2, no placeholder tab until it exists
const TABS: [Tab, string, Key][] = [
  ["reports", "/", "navReports"],
  ["chat", "/chat", "navChat"],
  ["profile", "/profile", "navProfile"],
];

/** Patient bottom nav: ink bar, magenta tick over the page you are on. */
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
              {t(key)}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
