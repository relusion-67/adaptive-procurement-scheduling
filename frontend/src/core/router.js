// A deliberately tiny hash router: this app has six screens and no nested
// layouts, so pulling in react-router would be dead weight on a low
// bandwidth connection. This gives real URLs, back-button support, and a
// navigate() function in ~35 lines.
import { useEffect, useState } from "react";

function readHash() {
  const hashPath = window.location.hash.replace(/^#/, "");
  const pathSource = hashPath || window.location.pathname || "/";
  const [path, query] = pathSource.split("?");
  const params = Object.fromEntries(new URLSearchParams(query));
  const segments = path.split("/").filter(Boolean);
  return { path, segments, params };
}

export function navigate(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  // Hash routes are the deploy-safe canonical format. Clear a pathname-only
  // deep link first so navigation never produces `/farmer#/staff`.
  if (window.location.pathname !== "/") {
    window.history.replaceState({}, "", "/");
  }
  window.location.hash = normalizedPath;
}

export function useHashRoute() {
  const [route, setRoute] = useState(readHash);

  useEffect(() => {
    const onHashChange = () => setRoute(readHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return route;
}
