import React from 'react';
import { CloudIcon, DatabaseIcon } from 'lucide-react';
import { MediaProviderStatus, StorageProvider } from '../../types';

type ProviderConnectProps = {
  statuses: Partial<Record<StorageProvider, MediaProviderStatus>>;
  onConnect: (provider: StorageProvider) => void;
  busyProvider?: StorageProvider | null;
};

const PROVIDER_METADATA: Record<
  Exclude<StorageProvider, 'local'>,
  { title: string; description: string; icon: React.ReactNode }
> = {
  supabase: {
    title: 'Supabase Storage',
    description: 'Streamlined uploads with signed URLs & CDN edge caching.',
    icon: <CloudIcon className="h-6 w-6 text-emerald-300" />,
  },
  gdrive: {
    title: 'Google Drive',
    description: 'Connect shared drives or service accounts for instant sync.',
    icon: <DatabaseIcon className="h-6 w-6 text-sky-300" />,
  },
};

const ProviderConnect: React.FC<ProviderConnectProps> = ({ statuses, onConnect, busyProvider }) => {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Object.entries(PROVIDER_METADATA).map(([provider, meta]) => {
        const status = statuses[provider as StorageProvider];
        const isConnected = status?.status === 'connected';
        const isMissingEnv = status?.status === 'missing_env';
        return (
          <div
            key={provider}
            className="flex flex-col gap-3 rounded-3xl border border-slate-800/70 bg-slate-900/70 p-5 shadow shadow-slate-900/40"
          >
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-slate-800/70 p-3">{meta.icon}</div>
              <div>
                <p className="font-semibold text-white">{meta.title}</p>
                <p className="text-sm text-slate-400">{meta.description}</p>
              </div>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  isConnected
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : isMissingEnv
                    ? 'bg-amber-500/20 text-amber-200'
                    : 'bg-slate-800 text-slate-300'
                }`}
              >
                {status ? status.status : 'Not connected'}
              </span>
              <button
                type="button"
                disabled={isMissingEnv || busyProvider === (provider as StorageProvider)}
                onClick={() => onConnect(provider as StorageProvider)}
                className="rounded-full bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 px-4 py-2 text-xs font-semibold text-white shadow shadow-indigo-900/50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyProvider === provider ? 'Checking...' : isConnected ? 'Refresh' : 'Connect'}
              </button>
            </div>
            {status?.details && <p className="text-xs text-slate-500">{status.details}</p>}
          </div>
        );
      })}
    </div>
  );
};

export default ProviderConnect;
