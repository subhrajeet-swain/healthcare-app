import { Account } from "../Account";
import type { Me } from "../api";
import { Band } from "../Band";
import { FamilySection } from "../Family";
import { useLang } from "../i18n";
import { Nav } from "../Nav";

type Props = { me: Me; onSignOut: () => void; onDeleted: () => void };

export function Profile({ me, onSignOut, onDeleted }: Props) {
  const { t } = useLang();
  return (
    <div className="shell">
      <Band
        line={me.name ? <span className="band__person">{me.name}</span> : undefined}
        initial={me.name?.trim().charAt(0).toUpperCase()}
      >
        <button className="btn btn--quiet" onClick={onSignOut}>
          {t("signOut")}
        </button>
      </Band>
      <main>
        <h1>{t("navProfile")}</h1>
        <Account me={me} onDeleted={onDeleted} />
        <FamilySection />
      </main>
      <Nav active="profile" />
    </div>
  );
}
