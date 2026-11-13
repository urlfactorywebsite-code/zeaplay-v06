/** One POST per credential. Web Locks serialize cooperating tabs on this origin.
 * A durable attempt marker also prevents retry after a tab crashes mid-request.
 */
export type SessionTokens = { access_token: string; refresh_token: string };
export class RefreshStorageUnavailableError extends Error {
  constructor() {
    super('Session recovery unavailable; sign in again');
    this.name = 'RefreshStorageUnavailableError';
  }
}
export function sessionIdentity(token: string | null): string | null {
  try {
    const claims = JSON.parse(atob((token || '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return claims.sid && claims.sub && claims.tenant_id
      ? `${claims.sub}:${claims.tenant_id}:${claims.sid}:${claims.auth_epoch}` : null;
  } catch { return null; }
}

function tokenId(token: string): string {
  const claims = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  if (typeof claims.jti !== 'string' || !claims.jti) throw new Error('Refresh credential requires sign-in');
  return claims.jti;
}

type Options = {
  getAccess(): string | null; getRefresh(): string | null;
  store(pair: SessionTokens): void; expire(): void;
  attempted(): string | null; markAttempt(id: string): void;
  waitForChange?(access: string | null, refresh: string): Promise<boolean>;
  request(token: string): Promise<SessionTokens>;
  lock?<T>(work: () => Promise<T>): Promise<T>;
};

export function createSessionRefresh(options: Options) {
  let pending: Promise<string | null> | null = null;
  let pendingIdentity: string | null = null;
  return function refresh(failedAccess: string | null): Promise<string | null> {
    const expected = sessionIdentity(failedAccess);
    if (pending) return pendingIdentity === expected ? pending
      : pending.then(() => refresh(failedAccess), () => refresh(failedAccess));
    pendingIdentity = expected;
    const work = async () => {
      const credential = options.getRefresh();
      const currentAccess = options.getAccess();
      if (!credential || !expected || sessionIdentity(credential) !== expected) return null;
      // A different tab already rotated while this request waited for the lock.
      if (currentAccess !== failedAccess && sessionIdentity(currentAccess) === expected) return currentAccess;
      const unchanged = () => options.getRefresh() === credential && options.getAccess() === currentAccess;
      try {
        const id = tokenId(credential);
        if (options.attempted() === id) {
          // A Web Lock handoff can precede delivery of another renderer's
          // localStorage events. Do not erase its successor from a stale cache.
          if (options.waitForChange) {
            if (await options.waitForChange(currentAccess, credential)) {
              const successor = options.getAccess();
              return successor !== failedAccess && sessionIdentity(successor) === expected
                && sessionIdentity(options.getRefresh()) === expected ? successor : null;
            }
            if (!unchanged()) return null;
            // No authoritative receipt: do not erase a newer pair hidden by
            // this renderer's stale cache. The caller expires only local UI.
            throw new RefreshStorageUnavailableError();
          }
          throw new Error('Refresh already attempted'); // Never POST it again.
        }
        options.markAttempt(id); // Storage failure must prevent the POST.
        const pair = await options.request(credential); // Deliberately no retry.
        if (!unchanged()) return null; // Logout/new login won the race.
        if (sessionIdentity(pair.access_token) !== expected || sessionIdentity(pair.refresh_token) !== expected
            || pair.refresh_token === credential) throw new Error('Invalid rotated session');
        options.store(pair);
        return pair.access_token;
      } catch (error) {
        if (error instanceof RefreshStorageUnavailableError) throw error;
        if (unchanged()) options.expire();
        return null;
      }
    };
    pending = (options.lock ? options.lock(work) : work()).catch(error => {
      if (error instanceof RefreshStorageUnavailableError) throw error;
      return null;
    }).finally(() => { pending = null; });
    return pending;
  };
}
