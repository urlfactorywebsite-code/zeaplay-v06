/** Fixed-window coalescing: bursts cannot starve the final authoritative read. */
export function coalesceActivityRefresh(run: () => void | Promise<unknown>, env = {
  later: (fn: () => void) => window.setTimeout(fn, 250),
  clear: (id: number) => window.clearTimeout(id),
}) {
  let timer: number | undefined;
  let running = false, pending = false;
  const finish = () => {
    running = false;
    if (pending) { pending = false; schedule(); }
  };
  const schedule = () => {
    if (timer !== undefined) return;
    timer = env.later(() => {
      timer = undefined; running = true;
      try {
        const result = run();
        if (result && typeof result.then === 'function') void result.then(finish, finish);
        else finish();
      } catch { finish(); } // Query state supplies errors; later events may retry.
    });
  };
  return {
    request() { if (running) pending = true; else schedule(); },
    cancel() { if (timer !== undefined) env.clear(timer); timer = undefined; pending = false; },
  };
}
