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

export function clearTokens(): void {
  clearPushBinding();
  avatarImageCache.clear();
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}
