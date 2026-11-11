/** One shared render clock; paused and hidden views consume no timer. */
export function createActivityClock(env: {
  now: () => number; hidden: () => boolean;
  every: (fn: () => void) => unknown; clear: (id: unknown) => void;
  onVisibility: (fn: () => void) => () => void;
}) {
  const listeners = new Set<() => void>();
  let tick = env.now(), timer: unknown, off: (() => void) | undefined;
  const publish = () => { tick = env.now(); for (const listener of listeners) listener(); };
  const visibility = () => {
    if (timer !== undefined) env.clear(timer);
    timer = undefined;
    if (listeners.size && !env.hidden()) { publish(); timer = env.every(publish); }
  };
  return {
    getSnapshot: () => tick,
    subscribe(listener: () => void) {
      listeners.add(listener);
      if (listeners.size === 1) { off = env.onVisibility(visibility); visibility(); }
      return () => {
        listeners.delete(listener);
        if (!listeners.size) {
          if (timer !== undefined) env.clear(timer);
          timer = undefined; off?.(); off = undefined;
        }
      };
    },
  };
}
