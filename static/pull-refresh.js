// Pull-down-to-refresh maths, kept apart from the page so it can be tested.

export const PULL_TRIGGER_PX = 70; // how far the indicator must travel before letting go refreshes
export const PULL_MAX_PX = 110; // never drawn further than this, however far the finger goes

// The finger travels `dy`; the indicator follows with resistance, like a rubber band.
export function pullDistance(dy) {
  if (dy <= 0) return 0;
  return Math.min(PULL_MAX_PX, dy * 0.5);
}

export function shouldRefresh(distance) {
  return distance >= PULL_TRIGGER_PX;
}

// A pull starts only from the very top, moving mostly down: a sideways swipe (the category row)
// or an upward scroll is left alone.
export function isPullingDown({ atTop, dx, dy }) {
  return atTop && dy > 8 && dy > Math.abs(dx) * 1.2;
}
