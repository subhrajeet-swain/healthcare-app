import type { ReactNode } from "react";
import { LangToggle } from "./i18n";

type Props = { line?: ReactNode; initial?: string; children?: ReactNode };

/** One row: a ringed mark (the patient's initial, else the brand's P), who this is, the language pill.
 * Extra actions (Sign out) get their own row below. */
export function Band({ line, initial, children }: Props) {
  return (
    <header className="band">
      <div className="band__row">
        <span className="band__mark" aria-hidden="true">{initial || "P"}</span>
        <div className="band__line">{line ?? <p className="band__name">Prime Healthcare</p>}</div>
        <LangToggle />
      </div>
      {children && <div className="band__row band__row--sub">{children}</div>}
    </header>
  );
}
