// A fair shuffle, and a way to keep one shuffled order for a whole session.
// Used by the Belval "which restaurant first?" vote (app.js): the four cards
// are shown in a random order per session so the one listed first doesn't win
// just for being first -- but the SAME order all session, so nothing jumps
// around under a person's thumb on a reload or when switching tabs.

/** Fisher-Yates: every ordering is equally likely (unlike sort(() => Math.random() - 0.5)). */
export function shuffled(items, random = Math.random) {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * The order to use for `names`: the one saved as JSON in `raw` if it is exactly
 * a permutation of `names` (same items, each once), otherwise a fresh shuffle.
 * `fresh` says a new order was made, i.e. the caller should save it.
 */
export function orderFromStorage(names, raw, random = Math.random) {
  try {
    const saved = JSON.parse(raw);
    if (
      Array.isArray(saved) &&
      saved.length === names.length &&
      new Set(saved).size === names.length &&
      names.every((n) => saved.includes(n))
    ) {
      return { order: saved, fresh: false };
    }
  } catch {
    /* nothing saved, or not JSON */
  }
  return { order: shuffled(names, random), fresh: true };
}
