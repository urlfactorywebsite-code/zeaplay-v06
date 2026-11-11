type AvatarAssetLike = {
  url?: string | null;
  dataUrl?: string | null;
  externalUrl?: string | null;
} | null | undefined;

export type AvatarSource = {
  profileImageUrl?: string | null;
  avatarUrl?: string | null;
  avatarAsset?: AvatarAssetLike;
} | null | undefined;

export const getUserAvatarUrl = (source: AvatarSource): string | null => {
  if (!source) {
    return null;
  }

  return [source.avatarAsset?.url, source.avatarUrl, source.profileImageUrl,
    source.avatarAsset?.dataUrl, source.avatarAsset?.externalUrl].map(value => value?.trim())
    .find(value => value && (/^\/(?!\/|\\)/.test(value) || /^https?:\/\//i.test(value)
      || /^data:image\/(?:png|jpeg|webp);base64,/i.test(value))) ?? null;
};


export const getAvatarInitials = (name: string): string => {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map(word => Array.from(word)[0]).join('').toUpperCase() || '?';
};

export const getAvatarColor = (identity: string): string => {
  const hash = Array.from(identity).reduce((value, char) => ((value * 31) + char.codePointAt(0)!) | 0, 0);
  return `hsl(${Math.abs(hash) % 360} 42% 30%)`;
};
