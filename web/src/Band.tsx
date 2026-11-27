import type { ReactNode } from "react";
import { ProfileSwitch, useProfile } from "./Family";
import { LangToggle, useLang } from "./i18n";

type Props = { line?: ReactNode; initial?: string; children?: ReactNode };

/** One row: a ringed mark (the patient's initial, else the brand's P), who this is, the language pill.
 * With family members, a row to switch whose reports these are; acting for one, the band names them.
 * Extra actions (Sign out) get their own row below. */
export function Band({ line, initial, children }: Props) {
  const { t } = useLang();
  const active = useProfile()?.active;
  if (active?.name) {
    line = (
      <>
        <span className="band__hello">{t("famActingFor")}</span>
        <span className="band__person">{active.name}</span>
      </>
    );
    initial = active.name.trim().charAt(0).toUpperCase();
  }
  return (
    <header className="band">
      <div className="band__row">
        <span className="band__mark" aria-hidden="true">{initial || "P"}</span>
        <div className="band__line">{line ?? <p className="band__name">Prime Healthcare</p>}</div>
        <LangToggle />
      </div>
      <ProfileSwitch />
      {children && <div className="band__row band__row--sub">{children}</div>}
    </header>
  );
}
