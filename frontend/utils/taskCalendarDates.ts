import { DateTime } from 'luxon';

/** Civil grid dates are placeholders for a day, not instants to convert to UTC. */
export function calendarDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function resolveTaskTimezone(profileZone?: string) {
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return profileZone && DateTime.now().setZone(profileZone).isValid ? profileZone : browserZone;
}

/** Existing naive backend timestamps represent UTC. */
export function parseTaskDate(value?: string | null) {
  if (!value) return new Date(NaN);
  const text = value.trim().replace(' ', 'T');
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : text.includes('T') ? `${text}Z` : `${text}T00:00:00Z`;
  return new Date(normalized);
}

export function taskDeadlineDateKey(value: string, timeZone = 'UTC') {
  const date = DateTime.fromJSDate(parseTaskDate(value)).setZone(timeZone);
  return date.isValid ? date.toISODate()! : '';
}

export function calendarToday(timeZone: string, instant = new Date()) {
  return new Date(`${DateTime.fromJSDate(instant).setZone(timeZone).toISODate()}T12:00:00`);
}

export function taskWallTimeToUtc(value: string, timeZone: string) {
  const date = DateTime.fromISO(value, { zone: timeZone });
  if (!date.isValid || date.toFormat("yyyy-MM-dd'T'HH:mm") !== value.slice(0, 16)) {
    throw new Error('This date/time is invalid in the selected timezone. Choose a valid local time.');
  }
  return date.toUTC().toISO()!;
}

/** Integer civil days keep timeline widths stable across DST and time offsets. */
export function taskTimelineRange(createdAt: string, dueAt: string | null, timeZone: string) {
  const ordinal = (value: string) => Date.parse(`${taskDeadlineDateKey(value, timeZone)}T00:00:00Z`) / 86_400_000;
  const created = ordinal(createdAt);
  const due = dueAt ? ordinal(dueAt) : created + 2;
  return { start: Math.min(created, due), end: Math.max(created, due), dueBeforeCreation: due < created };
}
