import { useCallback, useEffect, useState } from "react";
import { ApiError, type Me, api, messageFor } from "./api";
import { Band } from "./Band";
import { Consent } from "./pages/Consent";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Report } from "./pages/Report";
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

  useEffect(() => {
    const onPop = () => setPath(location.pathname);
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const loadMe = useCallback(async () => {
    setLoadError(null);
    try {
      const m = await api.me();
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
  if (route.name === "report") return <Report id={route.id} />;
  return <Dashboard me={me} onSignOut={signOut} onDeleted={signedOut} />;
}
