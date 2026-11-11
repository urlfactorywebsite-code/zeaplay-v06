import React, { useEffect, useState } from 'react';
import { Role } from '../types';
import { useOptionalAuth } from '../hooks/useAuth';
import api from '../services/mockApi';
import { AvatarSource, getAvatarInitials, getAvatarColor, getUserAvatarUrl } from '../utils/userAvatar';
import { getFrameClassName } from '../constants/avatarFrames';
import { avatarImageCache } from '../utils/avatarImageCache';
import { getAccessToken } from '../services/tokenStorage';

type Identity = NonNullable<AvatarSource> & { id?: string; name?: string; avatarFrame?: string | null; role?: Role };

/** One identity renderer, including authenticated images and broken-image fallback. */
export default function Avatar({ user, className = 'h-8 w-8', frame = true, size = 32 }: {
  user?: Identity | null; className?: string; frame?: boolean; size?: number;
}) {
  const auth = useOptionalAuth();
  const identity = user?.id && auth?.user?.id === user.id ? { ...user, ...auth.user } : user;
  const avatarUrl = getUserAvatarUrl(identity);
  const source = avatarUrl?.startsWith('/avatars/') && size <= 64
    ? `${avatarUrl}${avatarUrl.includes('?') ? '&' : '?'}thumbnail=true` : avatarUrl;
  const session = getAccessToken() || '';
  const key = `${session}:${source ?? ''}`;
  const [image, setImage] = useState<{ key: string; url: string | null }>({ key, url: null });
  const loaded = image.key === key ? image.url : null;
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    let release: (() => void) | undefined;
    setFailed(false);
    setReady(false);
    setImage({ key, url: null });
    if (source?.startsWith('/avatars/') || /^\/users\/[^/]+\/avatar-image/.test(source ?? '')) {
      const handle = avatarImageCache.acquire(source, session, () => api.getAvatarImage(source));
      release = handle.release;
      handle.promise.then(url => {
        if (!active) return;
        setImage({ key, url });
      }).catch(() => { if (active) setFailed(true); });
    } else {
      setImage({ key, url: source });
    }
    return () => { active = false; release?.(); };
  }, [source, session]);

  const name = identity?.name || 'User';
  const ring = frame ? getFrameClassName(identity?.avatarFrame || 'classic', identity?.role || Role.USER) : '';
  return <span role="img" aria-label={`${name} profile picture`} style={{ backgroundColor: getAvatarColor(identity?.id || name) }}
    className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full text-xs font-semibold text-white ${ring} ${className}`}>
    <span aria-hidden="true">{getAvatarInitials(name)}</span>
    {source && !failed && !ready && <span aria-hidden="true" className="absolute inset-0 animate-pulse bg-slate-700/60" />}
    {loaded && !failed && <img src={loaded} alt="" onLoad={() => setReady(true)} onError={() => setFailed(true)}
      className={`absolute inset-0 h-full w-full object-cover ${ready ? '' : 'opacity-0'}`} />}
  </span>;
}
