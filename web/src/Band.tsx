import type { ReactNode } from "react";
import { LangToggle } from "./i18n";

type Props = { line?: ReactNode; children?: ReactNode };

export function Band({ line, children }: Props) {
  return (
    <header className="band">
      <div className="band__row">
        <p className="band__name">Prime Healthcare</p>
        {children}
      </div>
      <div className="band__row band__row--sub">
        <p className="band__line">{line}</p>
        <LangToggle />
      </div>
    </header>
  );
}
