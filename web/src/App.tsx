import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Me, api, messageFor, setProfile } from "./api";
import { Band } from "./Band";
import { ProfileProvider } from "./Family";
import { Consent } from "./pages/Consent";
import { Dashboard } from "./pages/Dashboard";
import { Review } from "./pages/Doctor";
import { ChatPage } from "./pages/ChatPage";
import { Login } from "./pages/Login";
import { Profile } from "./pages/Profile";
import { Report } from "./pages/Report";
import { Shared } from "./pages/Shared";
import { Timeline } from "./pages/Timeline";
import { useLang } from "./i18n";
import { go, parseRoute } from "./routes";

const SLUG_KEY = "ph:lab";

function rememberSlug(slug: string) {
  try {
    localStorage.setItem(SLUG_KEY, slug);
  } catch {
    /* storage blocked: the login link still works */
  }
}

function lastSlug(): string | null {
  try {
    return localStorage.getItem(SLUG_KEY);
  } catch {
    return null;
  }
}

export default function App() {
  const { lang, t } = useLang();
  const [path, setPath] = useState(location.pathname);
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = loading
  const [loadError, setLoadError] = useState<{ error: unknown } | null>(null);

  // After an in-app move, put focus on the new page's heading so a screen reader announces
  // it (the tapped nav link unmounts with the old page). Skipped on first load.
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current) {
      moved.current = true;
      return;
    }
    const id = requestAnimationFrame(() => {
      const h = document.querySelector<HTMLElement>("main h1");
      h?.setAttribute("tabindex", "-1");
      h?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(id);
  }, [path]);

  useEffect(() => {
    const onPop = () => setPath(location.pathname);
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const loadMe = useCallback(async () => {
    if (parseRoute(location.pathname).name === "shared") return; // a doctor's link: no session to load
    setLoadError(null);
    try {
      const m = await api.me();
      if (m.role !== "patient") setProfile(null); // only patients act for family
      setMe(m);
      // keep deep links (/reports/:id); only leave the login and consent screens
      const here = parseRoute(location.pathname).name;
      if (!m.consent.core) go("/consent");
      else if (here === "login" || here === "consent") go("/");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else setLoadError({ error: e }); // server or network down: say so, never spin forever
    }
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const signedOut = useCallback(() => {
    setProfile(null);
    setMe(null);
    const slug = lastSlug();
    go(slug ? `/${slug}/login` : "/");
  }, []);

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined);
    signedOut();
  }, [signedOut]);

  const route = parseRoute(path);

  if (route.name === "login") {
    rememberSlug(route.slug);
    return <Login slug={route.slug} onSignedIn={loadMe} />;
  }
  if (route.name === "shared") return <Shared slug={route.slug} token={route.token} />;
  if (loadError) {
    return (
      <div className="shell">
        <Band />
        <main>
          <div className="msg msg--error" role="alert">
            <strong>{t("problem")}</strong>
            {messageFor(loadError.error, lang)}
          </div>
          <button className="btn" onClick={loadMe}>
            {t("tryAgain")}
          </button>
        </main>
      </div>
    );
  }
  if (me === undefined) {
    return (
      <div className="shell">
        <Band />
        <main aria-busy="true">
          <p className="lede">{t("loading")}</p>
        </main>
      </div>
    );
  }
  if (me === null) {
    const slug = lastSlug();
    return (
      <div className="shell">
        <Band />
        <main>
          <h1>{t("signedOut")}</h1>
          {slug ? (
            <a className="btn" href={`/${slug}/login`}>
              {t("signIn")}
            </a>
          ) : (
            <p className="lede">{t("openLink")}</p>
          )}
        </main>
      </div>
    );
  }
  if (route.name === "consent" || !me.consent.core) {
    return <Consent onAgreed={loadMe} onSignOut={signOut} />;
  }
  const patient = me.role === "patient";
  if (route.name === "review" && me.role === "doctor") return <Review key={route.id} id={route.id} />;
  const page =
    route.name === "report" ? (
      <Report id={route.id} nav={patient} />
    ) : patient && route.name === "chat" ? (
      <ChatPage />
    ) : patient && route.name === "timeline" ? (
      <Timeline />
    ) : patient && route.name === "profile" ? (
      <Profile me={me} onSignOut={signOut} onDeleted={signedOut} />
    ) : (
      <Dashboard me={me} onSignOut={signOut} onDeleted={signedOut} />
    );
  return patient ? <ProfileProvider>{page}</ProfileProvider> : page;
}
