export const LEGACY_CREDENTIAL_HISTORY_KEY = 'zea-play::bearer-key-history';
export const credentialHistoryKey = (userId: string) => `${LEGACY_CREDENTIAL_HISTORY_KEY}:${encodeURIComponent(userId)}`;

export function clearLegacyProviderCredentials(storage: Storage): void {
  for (const key of ['gemini-api-keys', 'gemini-api-usage', 'gemini-api-key-state']) storage.removeItem(key);
}

// Migrate only records whose issuer subject identifies this account. Unscoped
// legacy secrets must never hydrate into another account's integration screen.
export function readCredentialHistory(userId: string, persistent: Storage, session: Storage): unknown[] {
  const key = credentialHistoryKey(userId);
  try {
    const legacy = persistent.getItem(LEGACY_CREDENTIAL_HISTORY_KEY);
    const existing = session.getItem(key);
    const parsed: unknown = JSON.parse(existing ?? legacy ?? '[]');
    const records = Array.isArray(parsed) ? parsed.filter((record) =>
      typeof record === 'object' && record !== null && 'subject' in record && record.subject === userId,
    ) : [];
    if (legacy && !existing) session.setItem(key, JSON.stringify(records));
    persistent.removeItem(LEGACY_CREDENTIAL_HISTORY_KEY);
    return records;
  } catch { return []; }
}

export function clearCredentialHistory(session: Storage): void {
  Object.keys(session).filter((key) => key.startsWith(`${LEGACY_CREDENTIAL_HISTORY_KEY}:`)).forEach((key) => session.removeItem(key));
}
