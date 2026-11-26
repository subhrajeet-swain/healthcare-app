import { type FormEvent, Fragment, type ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
import { type Family, type Relation, api, getProfile, messageFor, setProfile } from "./api";
import { type Key, useLang } from "./i18n";

type Member = Family["members"][number];
type ProfileCtx = {
  family: Family | null;
  active: Member | null; // null: the signed-in patient themselves
  choose: (memberId: string | null) => void;
  reload: () => Promise<void>;
};
const Ctx = createContext<ProfileCtx | null>(null);

export const useProfile = () => useContext(Ctx);

/** Whom the patient is acting for. Switching remounts the pages, so every one reloads its data. */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const [family, setFamily] = useState<Family | null>(null);
  const [activeId, setActiveId] = useState(getProfile);

  const choose = useCallback((id: string | null) => {
    setProfile(id);
    setActiveId(id);
  }, []);

  const reload = useCallback(async () => {
    try {
      const f = await api.family();
      setFamily(f);
      // a profile that is no longer an active link (revoked, or from an old tab) falls back to Me
      const id = getProfile();
      if (id && !f.members.some((m) => m.member_id === id && m.status === "active")) choose(null);
    } catch {
      setFamily({ members: [], invites: [] });
      choose(null);
    }
  }, [choose]);

  useEffect(() => {
    reload();
  }, [reload]);

  const active = family?.members.find((m) => m.member_id === activeId && m.status === "active") ?? null;
  // with a stored profile, wait for the check rather than fire requests that may 404
  if (activeId && family === null) return null;
  return (
    <Ctx.Provider value={{ family, active, choose, reload }}>
      <Fragment key={activeId ?? "me"}>{children}</Fragment>
    </Ctx.Provider>
  );
}

/** "Me" plus each active member, as one pill like the language toggle. Hidden with no members. */
export function ProfileSwitch() {
  const { t } = useLang();
  const p = useProfile();
  const members = p?.family?.members.filter((m) => m.status === "active") ?? [];
  if (!p || members.length === 0) return null;
  return (
    <div className="band__row band__row--sub">
      <div className="toggle toggle--profiles" role="group" aria-label={t("famSwitch")}>
        <button className="toggle__btn" aria-pressed={p.active === null} onClick={() => p.choose(null)}>
          {t("famMe")}
        </button>
        {members.map((m) => (
          <button
            key={m.member_id}
            className="toggle__btn"
            aria-pressed={p.active?.member_id === m.member_id}
            onClick={() => p.choose(m.member_id)}
          >
            {m.name ?? t(RELATION[m.relation])}
          </button>
        ))}
      </div>
    </div>
  );
}

const RELATION: Record<Relation, Key> = {
  child: "famChild",
  parent: "famParent",
  spouse: "famSpouse",
  other: "famOther",
};

function useAct(onDone: () => Promise<void>) {
  const { lang } = useLang();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await onDone();
      return true;
    } catch (e) {
      setError(messageFor(e, lang));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, act };
}

function Problem({ text }: { text: string | null }) {
  const { t } = useLang();
  if (!text) return null;
  return (
    <div className="msg msg--error" role="alert">
      <strong>{t("problem")}</strong>
      {text}
    </div>
  );
}

function Row({ who, sub, children }: { who: string; sub: string; children: ReactNode }) {
  return (
    <li className="staff-row">
      <div className="staff-row__head">
        <span>
          <span className="report-row__what">{who}</span>
          {sub}
        </span>
      </div>
      <div className="actions family__actions">{children}</div>
    </li>
  );
}

/** Remove asks once: for a child it ends the only way to their reports. */
function RemoveButton({ label, onRemove, busy }: { label: Key; onRemove: () => void; busy: boolean }) {
  const { t } = useLang();
  const [sure, setSure] = useState(false);
  if (!sure)
    return (
      <button className="btn btn--quiet btn--small" onClick={() => setSure(true)} disabled={busy}>
        {t(label)}
      </button>
    );
  return (
    <>
      <button className="btn btn--danger btn--small" onClick={onRemove} disabled={busy} aria-busy={busy}>
        {t("famYesRemove")}
      </button>
      <button className="btn btn--quiet btn--small" onClick={() => setSure(false)} disabled={busy}>
        {t("famKeep")}
      </button>
    </>
  );
}

const ADD: Relation[] = ["child", "parent", "spouse", "other"];

function AddForm({ onDone }: { onDone: () => Promise<void> }) {
  const { t } = useLang();
  const [relation, setRelation] = useState<Relation>("child");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [added, setAdded] = useState<Key | null>(null);
  const { busy, error, act } = useAct(onDone);
  const child = relation === "child";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setAdded(null);
    const ok = await act(() => (relation === "child" ? api.addChild(name) : api.invite(relation, name, phone)));
    if (ok) {
      setAdded(child ? "famChildAdded" : "famInvited");
      setName("");
      setPhone("");
    }
  }

  return (
    <form className="strip__body" onSubmit={submit} aria-labelledby="fam-add-title" noValidate>
      <h3 className="family__sub" id="fam-add-title">{t("famAdd")}</h3>
      <div className="field">
        <span id="fam-rel-label" className="family__label">{t("famWho")}</span>
        <div className="toggle toggle--flat" role="group" aria-labelledby="fam-rel-label">
          {ADD.map((r) => (
            <button key={r} type="button" className="toggle__btn" aria-pressed={relation === r} onClick={() => {
                setRelation(r);
                setAdded(null);
              }}>
              {t(RELATION[r])}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="fam-name">{t("famName")}</label>
        <input id="fam-name" className="text text--boxed" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      {child ? (
        <p className="field__hint">{t("famChildConsent")}</p>
      ) : (
        <div className="field">
          <label htmlFor="fam-phone">{t("mobileNumber")}</label>
          <div className="phone">
            <span aria-hidden="true">+91</span>
            <input id="fam-phone" className="text" type="tel" inputMode="numeric" value={phone} onChange={(e) => setPhone(e.target.value)} aria-describedby="fam-phone-hint" required />
          </div>
          <span id="fam-phone-hint" className="field__hint">{t("famInviteHint")}</span>
        </div>
      )}
      <Problem text={error} />
      {added && <div className="msg msg--info" role="status">{t(added)}</div>}
      <button className="btn" type="submit" disabled={busy} aria-busy={busy}>
        {busy ? t("saving") : t(child ? "famAddChild" : "famSendInvite")}
      </button>
    </form>
  );
}

/** Profile page: the people I manage, the people who asked to manage me, and adding someone. */
export function FamilySection() {
  const { t } = useLang();
  const p = useProfile();
  const reload = p?.reload ?? (async () => undefined);
  const { busy, error, act } = useAct(reload);
  if (!p?.family) return null;
  const { members, invites } = p.family;

  return (
    <section className="strip" aria-labelledby="family-title">
      <div className="strip__head">
        <h2 className="strip__title" id="family-title">{t("famTitle")}</h2>
      </div>
      <div className="strip__body">
        <p>{t("famLede")}</p>
        <Problem text={error} />
      </div>
      {(members.length > 0 || invites.length > 0) && (
        <ul className="perf-list">
          {members.map((m) => (
            <Row
              key={m.link_id}
              who={m.name ?? t(RELATION[m.relation])}
              sub={`${t(RELATION[m.relation])} · ${t(m.status === "active" ? "famActive" : "famWaiting")}`}
            >
              <RemoveButton label="famRemove" busy={busy} onRemove={() => act(() => api.revokeLink(m.link_id))} />
            </Row>
          ))}
          {invites.map((i) => (
            <Row
              key={i.link_id}
              who={i.name ?? ""}
              sub={t(i.status === "pending" ? "famAsks" : "famManages")}
            >
              {i.status === "pending" && (
                <button className="btn btn--small" disabled={busy} onClick={() => act(() => api.acceptInvite(i.link_id))}>
                  {t("famAccept")}
                </button>
              )}
              <RemoveButton
                label={i.status === "pending" ? "famDecline" : "famStop"}
                busy={busy}
                onRemove={() => act(() => api.revokeLink(i.link_id))}
              />
            </Row>
          ))}
        </ul>
      )}
      <AddForm onDone={reload} />
    </section>
  );
}
