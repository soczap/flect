/* Hash router: #/incidents/11 → { view: "incidents", arg: "11" }. Deep links survive reloads. */
import { useSyncExternalStore } from "react";

export const VIEW_IDS = ["overview", "incidents", "prs", "traffic", "deploys", "keys", "reports", "audit", "settings"] as const;
export type ViewId = (typeof VIEW_IDS)[number];

const EVENT = "flect:route";

function read() {
  const [v = "", arg = ""] = location.hash.replace(/^#\/?/, "").split("/");
  const view = (VIEW_IDS as readonly string[]).includes(v) ? (v as ViewId) : "overview";
  return `${view}/${decodeURIComponent(arg)}`;
}

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  window.addEventListener("popstate", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("hashchange", cb);
    window.removeEventListener("popstate", cb);
    window.removeEventListener(EVENT, cb);
  };
}

export function useRoute(): { view: ViewId; arg: string } {
  const key = useSyncExternalStore(subscribe, read);
  const i = key.indexOf("/");
  return { view: key.slice(0, i) as ViewId, arg: key.slice(i + 1) };
}

export const href = (view: ViewId, arg?: string | number) => `#/${view}${arg != null && arg !== "" ? `/${arg}` : ""}`;

/** Navigate. Entries pushed here are marked so a closing drawer can step back to where you were. */
export function go(view: ViewId, arg?: string | number, replace = false) {
  const next = href(view, arg);
  if (location.hash === next) return;
  if (replace) history.replaceState(history.state, "", next);
  else history.pushState({ inApp: true }, "", next);
  window.dispatchEvent(new Event(EVENT));
}

/** Close a drawer: return to the page that opened it, or to the view's list on a cold deep link. */
export function closeTo(view: ViewId) {
  if ((history.state as { inApp?: boolean } | null)?.inApp) history.back();
  else go(view, undefined, true);
}

/** Route in-app hash links through go() so they get the in-app marker; modified clicks behave normally. */
export function interceptLinks(e: MouseEvent) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = (e.target as Element | null)?.closest?.("a[href^='#/']");
  if (!a || a.getAttribute("target")) return;
  const [v = "", arg] = (a.getAttribute("href") || "").replace(/^#\/?/, "").split("/");
  if (!(VIEW_IDS as readonly string[]).includes(v)) return;
  e.preventDefault();
  go(v as ViewId, arg);
}
