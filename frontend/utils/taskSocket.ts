export function taskReconnectDelay(attempt: number, random: number) {
  return Math.min(15_000, Math.round(1000 * 2 ** Math.min(attempt, 4) * (0.75 + Math.max(0, Math.min(1, random)) / 2)));
}
