import { useCallback, useEffect, useState } from "react";
import { ApiError, type Me, api } from "./api";
import { Band } from "./Band";
import { Consent } from "./pages/Consent";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
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
  const [path, setPath] = useState(location.pathname);
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = loading

  useEffect(() => {
    const onPop = () => setPath(location.pathname);
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const loadMe = useCallback(async () => {
    try {
      const m = await api.me();
      setMe(m);
      go(m.consent.core ? "/" : "/consent");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else throw e;
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
  if (me === undefined) {
    return (
      <div className="shell">
        <Band />
        <main aria-busy="true">
          <p className="lede">Loading…</p>
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
          <h1>You're signed out</h1>
          {slug ? (
            <a className="btn" href={`/${slug}/login`}>
              Sign in
            </a>
          ) : (
            <p className="lede">Open the sign-in link your lab sent you by SMS or WhatsApp.</p>
          )}
        </main>
      </div>
    );
  }
  if (route.name === "consent" || !me.consent.core) {
    return <Consent onAgreed={loadMe} onSignOut={signOut} />;
  }
  return <Dashboard me={me} onSignOut={signOut} onDeleted={signedOut} />;
}
