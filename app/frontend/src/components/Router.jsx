/** @fileoverview Minimal pushState router with Preact signals. */
import { signal } from "@preact/signals";

/** Current pathname signal — drives all route matching. */
export const route = signal(window.location.pathname);

/**
 * Navigate to a new path via pushState, updating the route signal.
 * @param {string} path - Target pathname
 */
export function navigate(path) {
  if (path === route.value) return;
  window.history.pushState(null, "", path);
  route.value = path;
}

// Back/forward browser navigation
window.addEventListener("popstate", () => {
  route.value = window.location.pathname;
});

/**
 * Router — renders the first matching route.
 * Match priority: exact path > prefix match > wildcard ("*").
 *
 * @param {Object}   props
 * @param {Array}    props.routes  [{path, component}]
 *   path="/"         exact match
 *   path="/display"  prefix match (matches /display, /display/foo, etc.)
 *   path="*"         wildcard fallback
 */
export function Router({ routes = [] }) {
  const current = route.value;

  // 1. Exact match
  for (const r of routes) {
    if (r.path !== "*" && current === r.path) {
      const C = r.component;
      return <C />;
    }
  }

  // 2. Prefix match (longest first)
  const prefixRoutes = routes
    .filter((r) => r.path !== "*" && r.path !== "/" && current.startsWith(r.path))
    .sort((a, b) => b.path.length - a.path.length);

  if (prefixRoutes.length > 0) {
    const C = prefixRoutes[0].component;
    return <C />;
  }

  // 3. Wildcard fallback
  const wildcard = routes.find((r) => r.path === "*");
  if (wildcard) {
    const C = wildcard.component;
    return <C />;
  }

  return null;
}
