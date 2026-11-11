import { useCallback, useEffect, useState } from 'react';
import { AvatarAsset } from '../types';
import api from '../services/mockApi';

interface UseAvatarLibraryResult {
  avatars: AvatarAsset[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setAvatars: React.Dispatch<React.SetStateAction<AvatarAsset[]>>;
}

export function useAvatarLibrary(): UseAvatarLibraryResult {
  const [avatars, setAvatars] = useState<AvatarAsset[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAvatars((await api.getAvatarAssets()).filter(asset => asset.isDefault));
    } catch (err) {
      setAvatars([]);
      setError(err instanceof Error ? err.message : 'Unable to load avatars');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { avatars, loading, error, refresh, setAvatars };
}
