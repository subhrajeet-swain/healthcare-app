import type { ReactNode } from "react";

type Props = { line?: ReactNode; children?: ReactNode };

export function Band({ line, children }: Props) {
  return (
    <header className="band">
      <div className="band__row">
        <div>
          <p className="band__name">Prime Healthcare</p>
          {line && <p className="band__line">{line}</p>}
        </div>
        {children}
      </div>
    </header>
  );
}
