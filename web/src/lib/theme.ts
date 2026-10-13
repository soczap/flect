import { useEffect, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "flect-theme";
const EVENT = "flect:theme";

const current = (): Theme => (document.documentElement.dataset.theme === "light" ? "light" : "dark");

function saved(): Theme | null {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : null;
  } catch {
    return null;
  }
}

function apply(t: Theme) {
  document.documentElement.dataset.theme = t;
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}

export function toggleTheme() {
  const next: Theme = current() === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
  apply(next);
}

/** index.html sets data-theme before paint; until the user picks, the page follows the OS. */
export function useFollowOsTheme() {
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: light)");
    const onChange = () => !saved() && apply(mq.matches ? "light" : "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
}

export function useTheme(): [Theme, () => void] {
  return [useSyncExternalStore(subscribe, current), toggleTheme];
}
