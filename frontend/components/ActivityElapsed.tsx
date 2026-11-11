import React, { useSyncExternalStore } from 'react';
import type { ActivityContext } from '../types/taskActivity';
import { elapsedSeconds, workDuration } from '../utils/taskActivity';
import { createActivityClock } from '../utils/activityClock';

const clock = createActivityClock({
  now: () => performance.now(), hidden: () => document.hidden,
  every: fn => window.setInterval(fn, 1000), clear: id => window.clearInterval(id as number),
  onVisibility: fn => { document.addEventListener('visibilitychange', fn); return () => document.removeEventListener('visibilitychange', fn); },
});
const idle = () => () => {};
/** Only this text updates each second; forms, slot cards and Luxon stay idle. */
export default React.memo(function ActivityElapsed({ row, receivedAt, selected = false }: {
  row: ActivityContext; receivedAt: number; selected?: boolean;
}) {
  const tick = useSyncExternalStore(row.status === 'RUNNING' ? clock.subscribe : idle, clock.getSnapshot);
  return <>{workDuration(elapsedSeconds(row, receivedAt, tick, selected))}</>;
});
