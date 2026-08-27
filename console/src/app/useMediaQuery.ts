import { useEffect, useState } from "react";

export const STACKED_QUERY = "(max-width: 800px)";
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function queryList(query: string): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query)
    : null;
}

/** Tracks a CSS media query; false only when `matchMedia` is unavailable. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => queryList(query)?.matches ?? false);

  useEffect(() => {
    const list = queryList(query);
    if (list === null) return undefined;
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matches;
}
