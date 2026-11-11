import assert from 'node:assert/strict';
import test from 'node:test';
import { clearCredentialHistory, clearLegacyProviderCredentials, credentialHistoryKey, LEGACY_CREDENTIAL_HISTORY_KEY, readCredentialHistory } from '../utils/credentialHistory';

const storage = (): Storage => {
  const values: Record<string, string> = {};
  return new Proxy(values, {
    get(target, key) {
      if (key === 'getItem') return (name: string) => target[name] ?? null;
      if (key === 'setItem') return (name: string, value: string) => { target[name] = value; };
      if (key === 'removeItem') return (name: string) => { delete target[name]; };
      return target[String(key)];
    },
  }) as unknown as Storage;
};

test('migrates only credential records owned by the current account', () => {
  const persistent = storage(); const session = storage();
  persistent.setItem(LEGACY_CREDENTIAL_HISTORY_KEY, JSON.stringify([
    { id: 'mine', key: 'fixture-key', subject: 'owner-a' },
    { id: 'other', key: 'other-key', subject: 'owner-b' },
    { id: 'unknown', key: 'unscoped-key' },
  ]));
  assert.deepEqual(readCredentialHistory('owner-a', persistent, session), [{ id: 'mine', key: 'fixture-key', subject: 'owner-a' }]);
  assert.equal(persistent.getItem(LEGACY_CREDENTIAL_HISTORY_KEY), null);
  assert.deepEqual(readCredentialHistory('owner-a', persistent, session), [{ id: 'mine', key: 'fixture-key', subject: 'owner-a' }], 'StrictMode second initialization must retain migrated keys');
});

test('credential histories are isolated by account and malformed input is ignored', () => {
  const persistent = storage(); const session = storage();
  session.setItem(credentialHistoryKey('owner-a'), JSON.stringify([{ id: 'mine', subject: 'owner-a', key: 'fixture-key' }]));
  assert.deepEqual(readCredentialHistory('owner-b', persistent, session), []);
  session.setItem(credentialHistoryKey('owner-b'), 'malformed');
  assert.deepEqual(readCredentialHistory('owner-b', persistent, session), []);
});

test('logout clears credential histories while preserving unrelated preferences', () => {
  const session = storage();
  session.setItem(credentialHistoryKey('owner-a'), 'fixture-history');
  session.setItem('unrelated-preference', 'retained');
  clearCredentialHistory(session);
  assert.equal(session.getItem(credentialHistoryKey('owner-a')), null);
  assert.equal(session.getItem('unrelated-preference'), 'retained');
});

test('retired browser provider caches are cleared without resetting preferences', () => {
  const persistent = storage();
  for (const key of ['gemini-api-keys', 'gemini-api-usage', 'gemini-api-key-state']) persistent.setItem(key, 'fixture-secret');
  persistent.setItem('gemini-api-daily-limit', '60');
  persistent.setItem('zenith-task-theme', 'dark');
  clearLegacyProviderCredentials(persistent);
  assert.equal(persistent.getItem('gemini-api-keys'), null);
  assert.equal(persistent.getItem('gemini-api-usage'), null);
  assert.equal(persistent.getItem('gemini-api-key-state'), null);
  assert.equal(persistent.getItem('gemini-api-daily-limit'), '60');
  assert.equal(persistent.getItem('zenith-task-theme'), 'dark');
});
