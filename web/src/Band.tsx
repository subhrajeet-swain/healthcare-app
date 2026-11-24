import type { ReactNode } from "react";

export function Band({ children }: { children?: ReactNode }) {
  return (
    <header className="band">
      <div className="band__row">
        <p className="band__name">Prime Healthcare</p>
        {children}
      </div>
    </header>
  );
}
