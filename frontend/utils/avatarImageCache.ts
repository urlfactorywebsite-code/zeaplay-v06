/** Authenticated images stay in memory, scoped to the current login. */
export function createAvatarImageCache(
  createUrl = (blob: Blob) => URL.createObjectURL(blob),
  revokeUrl = (url: string) => URL.revokeObjectURL(url),
  now = () => Date.now(),
) {
  type Entry = { promise: Promise<string>; refs: number; used: number; url?: string };
  const entries = new Map<string, Entry>();
  let session: string | null = null;
  const drop = (key: string, entry: Entry) => {
    entries.delete(key);
    if (entry.url) revokeUrl(entry.url);
  };
  const clear = () => { for (const [key, entry] of entries) drop(key, entry); session = null; };
  return {
    clear,
    acquire(source: string, scope: string, load: () => Promise<Blob>) {
      if (session !== scope) { clear(); session = scope; }
      for (const [key, entry] of entries) {
        if (!entry.refs && (now() - entry.used > 300_000 || entries.size >= 64)) drop(key, entry);
      }
      let entry = entries.get(source);
      if (!entry) {
        entry = { refs: 0, used: now(), promise: Promise.resolve('') };
        const current = entry;
        entries.set(source, entry);
        entry.promise = load().then(blob => {
          if (entries.get(source) !== current) throw new Error('Avatar session changed');
          // SVG is returned only for the server's immutable packaged artwork.
          if (!/^image\/(?:png|jpeg|webp|svg\+xml)$/.test(blob.type)) throw new Error('Invalid avatar response');
          current.url = createUrl(blob);
          return current.url;
        }).catch(error => {
          if (entries.get(source) === current) drop(source, current);
          throw error;
        });
      }
      entry.refs++;
      const current = entry;
      let released = false;
      return { promise: entry.promise, release() {
        if (!released) { released = true; current.refs--; current.used = now(); }
      } };
    },
  };
}

export const avatarImageCache = createAvatarImageCache();
