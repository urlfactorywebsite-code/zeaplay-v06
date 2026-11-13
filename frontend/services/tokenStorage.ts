import { avatarImageCache } from '../utils/avatarImageCache';
import { clearPushBinding } from '../utils/pushBinding';

const ACCESS_TOKEN_KEY = 'vee_access_token';
const REFRESH_TOKEN_KEY = 'vee_refresh_token';

export function storeTokens(accessToken: string, refreshToken: string): void {
  // Refreshes retain the same device binding; account changes clear old cards.
  const subject = (token: string | null) => {
    try { const payload = JSON.parse(atob((token || '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); return `${payload.sub}:${payload.tenant_id ?? ''}`; }
    catch { return token; }
  };
  if (subject(getAccessToken()) !== subject(accessToken)) clearPushBinding();
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function getAccessToken(): string | null {
  try { return localStorage.getItem(ACCESS_TOKEN_KEY); } catch { return null; }
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

/** Wait for a completed credential update after a cross-renderer lock handoff.
 * The deadline bounds a lost issuer/response; it is not a delay before refresh.
 * No token is sent or broadcast and no refresh POST is retried here.
 */
export function waitForTokenChange(access: string | null, refresh: string): Promise<boolean> {
  if (typeof window === 'undefined') return Promise.resolve(false);
  return new Promise(resolve => {
    let timer: ReturnType<typeof setTimeout>;
    const complete = (changed: boolean) => {
      clearTimeout(timer);
      window.removeEventListener('storage', received);
      resolve(changed);
    };
    const check = () => {
      // Both values must change: never publish half of the two-key update.
      if (getAccessToken() !== access && getRefreshToken() !== refresh) complete(true);
    };
    const received = (event: StorageEvent) => {
      if (event.storageArea === localStorage && (event.key === null
          || event.key === ACCESS_TOKEN_KEY || event.key === REFRESH_TOKEN_KEY)) check();
    };
    window.addEventListener('storage', received);
    timer = setTimeout(() => complete(false), 8000);
    check(); // Covers a receipt arriving immediately before listener attachment.
  });
}

export function clearTokens(): void {
  clearPushBinding();
  avatarImageCache.clear();
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}
