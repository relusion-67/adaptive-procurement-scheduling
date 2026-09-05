// A deliberately tiny hash router: this app has six screens and no nested
// layouts, so pulling in react-router would be dead weight on a low
// bandwidth connection. This gives real URLs, back-button support, and a
// navigate() function in ~35 lines.
import { useEffect, useState } from "react";

function readHash() {
  const hash = window.location.hash.replace(/^#/, "") || "/";
  const [path, query] = hash.split("?");
  const params = Object.fromEntries(new URLSearchParams(query));
  const segments = path.split("/").filter(Boolean);
  return { path, segments, params };
}

export function navigate(path) {
  window.location.hash = path;
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
