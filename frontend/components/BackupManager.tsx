import { APP_VERSION_LABEL } from '../utils/appVersion';
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Archive,
  ArrowDownToLine,
  Check,
  Copy,
  Database,
  FileUp,
  History,
  LoaderCircle,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { http } from '../services/mockApi';

type Settings = {
  scope: 'all' | 'custom';
  datasets: string[];
  format: 'csv' | 'json';
  packaging: 'zip';
  include_related: boolean;
  acknowledge_dependencies: boolean;
};
type Dataset = {
  id: string;
  name: string;
  count: number;
  description: string;
  dependencies: string[];
};
type Preset = { id: string; name: string; settings: Settings };
type Report = {
  datasets?: Record<string, number>;
  selected?: string[];
  mode?: 'insert' | 'update';
  errors?: string[];
  warnings?: string[];
  valid?: boolean;
  impact?: Record<string, number>;
  preview_token?: string;
  progress?: { completed_files: number; total_files: number };
};
type Job = {
  id: string;
  operation: string;
  scope: string;
  requested_by: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  record_count: number;
  file_size: number;
  error: string | null;
  download_available: boolean;
  report: Report;
};
const initial: Settings = {
  scope: 'all',
  datasets: [],
  format: 'csv',
  packaging: 'zip',
  include_related: true,
  acknowledge_dependencies: false,
};
const base = '/admin/data/manager';
const field =
  'w-full rounded-lg border border-border-color bg-background px-3 py-2 text-sm text-text-primary focus:border-primary focus:outline-none';
const button =
  'inline-flex items-center justify-center gap-2 rounded-lg border border-border-color px-3 py-2 text-sm font-medium text-text-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed';
const primary = `${button} bg-primary text-white border-primary hover:bg-primary/90`;
const utc = (value: string) =>
  new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString();
const errorText = (error: any) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string'
    ? detail
    : error instanceof Error
      ? error.message
      : 'Request failed. Please retry.';
};

export default function BackupManager({
  requestedBy,
  initialTab = 'export',
  initialDataset = '',
  initialFile = null,
  onRestored,
}: {
  requestedBy: string;
  initialTab?: 'export' | 'import' | 'history';
  initialDataset?: string;
  initialFile?: File | null;
  onRestored?: () => void;
}) {
  const [tab, setTab] = useState<'export' | 'import' | 'history'>(initialTab);
  const [settings, setSettings] = useState<Settings>(initial);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [unknown, setUnknown] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState('');
  const [saveConfig, setSaveConfig] = useState(false);
  const [configName, setConfigName] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [message, setMessage] = useState<{
    text: string;
    error?: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(initialFile);
  const [legacyDataset, setLegacyDataset] = useState(initialDataset);
  const [importJob, setImportJob] = useState<Job | null>(null);
  const [restoreSelected, setRestoreSelected] = useState<string[]>([]);
  const [restoreMode, setRestoreMode] = useState<'insert' | 'update'>('insert');
  const [provisionUsers, setProvisionUsers] = useState(false);
  const [previewCurrent, setPreviewCurrent] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [summaryTime, setSummaryTime] = useState(() =>
    new Date().toLocaleString(),
  );
  const activeDownload = useRef<string | null>(null);
  const downloaded = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    const [catalog, configurations, history] = await Promise.all([
      http.get(`${base}/catalog`),
      http.get(`${base}/presets`),
      http.get(`${base}/jobs`),
    ]);
    setDatasets(catalog.data.datasets);
    setLimitations(catalog.data.limitations);
    setUnknown(catalog.data.unregistered_tables);
    setPresets(configurations.data);
    setJobs(history.data);
  }, []);

  const download = useCallback(async (id: string) => {
    setDownloading(id);
    try {
      const { data } = await http.post(`${base}/jobs/${id}/download-ticket`);
      const anchor = document.createElement('a');
      anchor.href = http.getUri({
        url: `${base}/jobs/${id}/download`,
        params: { ticket: data.ticket },
      });
      anchor.referrerPolicy = 'no-referrer';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setMessage({
        text: 'Archive download requested. Backups expire after 24 hours; store this sensitive file securely.',
      });
    } catch (error) {
      setMessage({ text: errorText(error), error: true });
    } finally {
      setDownloading(null);
    }
  }, []);

  useEffect(() => {
    refresh().catch((error) =>
      setMessage({ text: errorText(error), error: true }),
    );
  }, [refresh]);
  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const { data } = await http.get<Job[]>(`${base}/jobs`, {
          showGlobalProgress: false,
        });
        if (!mounted) return;
        setJobs(data);
        const job = data.find((item) => item.id === activeDownload.current);
        if (job?.status === 'Completed' && !downloaded.current.has(job.id)) {
          downloaded.current.add(job.id);
          activeDownload.current = null;
          await download(job.id);
        } else if (job && ['Failed', 'Cancelled'].includes(job.status)) {
          activeDownload.current = null;
          setMessage({ text: job.error || 'Export cancelled.', error: true });
        }
      } catch (error) {
        if (mounted) setMessage({ text: errorText(error), error: true });
      }
      if (mounted) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => {
      mounted = false;
      clearTimeout(timer);
    };
  }, [download]);

  const selected = useMemo(() => {
    const chosen = new Set(
      settings.scope === 'all' ? datasets.map((d) => d.id) : settings.datasets,
    );
    if (settings.include_related) {
      let last = -1;
      while (last !== chosen.size) {
        last = chosen.size;
        datasets
          .filter((d) => chosen.has(d.id))
          .forEach((d) =>
            d.dependencies.forEach((dep) => {
              if (datasets.some((d) => d.id === dep)) chosen.add(dep);
            }),
          );
      }
    }
    return datasets.filter((d) => chosen.has(d.id));
  }, [settings, datasets]);
  const missing = Array.from(
    new Set(
      selected
        .flatMap((d) => d.dependencies)
        .filter((dep) => !selected.some((d) => d.id === dep)),
    ),
  );
  const exportRunning = jobs.some(
    (job) =>
      job.operation === 'Export' &&
      ['Queued', 'Processing'].includes(job.status),
  );
  const filtered = datasets.filter((d) =>
    `${d.name} ${d.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  const update = (patch: Partial<Settings>) => {
    setSettings((current) => ({
      ...current,
      ...patch,
      acknowledge_dependencies: patch.acknowledge_dependencies ?? false,
    }));
    setSummaryTime(new Date().toLocaleString());
  };
  const toggle = (id: string) =>
    update({
      scope: 'custom',
      datasets: selected.some((d) => d.id === id)
        ? selected.filter((d) => d.id !== id).map((d) => d.id)
        : [...selected.map((d) => d.id), id],
    });
  const withBusy = async (action: () => Promise<void>) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch (error) {
      setMessage({ text: errorText(error), error: true });
    } finally {
      setBusy(false);
    }
  };

  const savePreset = async (duplicate = false) => {
    if (!configName.trim()) throw new Error('Configuration name is required.');
    const payload = {
      name: duplicate ? `${configName} (copy)` : configName,
      settings,
    };
    const { data } =
      presetId && !duplicate
        ? await http.put(`${base}/presets/${presetId}`, payload)
        : await http.post(`${base}/presets`, payload);
    setPresetId(data.id);
    await refresh();
    setMessage({ text: 'Export configuration saved.' });
  };
  const generate = () =>
    withBusy(async () => {
      if (saveConfig) await savePreset();
      const { data } = await http.post<Job>(`${base}/exports`, settings);
      activeDownload.current = data.id;
      setJobs((current) => [data, ...current]);
      setMessage({
        text: 'Export queued. The archive will download once this job completes. You can also download it from history.',
      });
    });
  const validate = () =>
    withBusy(async () => {
      if (!file) throw new Error('Select a backup file.');
      setImportJob(null);
      setPreviewCurrent(false);
      setConfirmation('');
      const form = new FormData();
      form.append('file', file);
      if (legacyDataset) form.append('dataset', legacyDataset);
      const { data } = await http.post<Job>(`${base}/imports/validate`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setImportJob(data);
      setRestoreSelected(Object.keys(data.report.datasets || {}));
      setRestoreMode('insert');
      setProvisionUsers(false);
      setPreviewCurrent(true);
      await refresh();
    });
  const preview = () =>
    withBusy(async () => {
      const { data } = await http.post<Job>(
        `${base}/imports/${importJob!.id}/preview`,
        {
          selected: restoreSelected,
          mode: restoreMode,
          provision_users: provisionUsers,
        },
      );
      setImportJob(data);
      setPreviewCurrent(true);
      setConfirmation('');
    });
  const confirm = () =>
    withBusy(async () => {
      const { data } = await http.post<Job>(
        `${base}/imports/${importJob!.id}/confirm`,
        { confirmation, preview_token: importJob!.report.preview_token },
      );
      setImportJob(data);
      setPreviewCurrent(false);
      setConfirmation('');
      setMessage({
        text: 'Restore completed in one transaction. Refresh application views to see restored data.',
      });
      onRestored?.();
      await refresh();
    });

  return (
    <div className="space-y-6 text-text-primary">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex gap-3">
          <div className="rounded-xl bg-primary/10 p-3 text-primary">
            <Database size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold">Export & Import Manager</h2>
            <p className="mt-1 text-sm text-text-secondary">
              Manage workspace backups, saved configurations, and validated
              restores.
            </p>
          </div>
        </div>
        <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs text-primary">
          Owner access · {APP_VERSION_LABEL}
        </span>
      </header>
      <nav
        aria-label="Backup manager"
        className="flex gap-2 border-b border-border-color pb-3"
      >
        {(['export', 'import', 'history'] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`${button} ${tab === value ? 'bg-primary/10 border-primary/40 text-primary' : ''}`}
          >
            {value === 'export' ? (
              <Archive size={16} />
            ) : value === 'import' ? (
              <FileUp size={16} />
            ) : (
              <History size={16} />
            )}
            {value === 'export'
              ? 'New Export'
              : value === 'import'
                ? 'Import / Restore'
                : 'History'}
          </button>
        ))}
      </nav>
      {message && (
        <div
          role={message.error ? 'alert' : 'status'}
          className={`rounded-lg border p-3 text-sm ${message.error ? 'border-red-500/40 bg-red-500/10 text-red-400' : 'border-primary/30 bg-primary/10'}`}
        >
          {message.text}
        </div>
      )}
      {tab === 'export' && (
        <div className="grid xl:grid-cols-[minmax(0,1fr)_300px] gap-6">
          <div className="space-y-6">
            <section className="space-y-3">
              <h3 className="font-semibold">Export mode</h3>
              <div className="grid sm:grid-cols-2 gap-3">
                {(['all', 'custom'] as const).map((scope) => (
                  <button
                    key={scope}
                    type="button"
                    aria-pressed={settings.scope === scope}
                    onClick={() => update({ scope })}
                    className={`rounded-xl border p-4 text-left ${settings.scope === scope ? 'border-primary bg-primary/10' : 'border-border-color bg-background'}`}
                  >
                    <span className="flex items-center justify-between font-medium">
                      {scope === 'all'
                        ? 'Entire Workspace'
                        : 'Custom Selection'}
                      {settings.scope === scope && (
                        <Check size={18} className="text-primary" />
                      )}
                    </span>
                    <span className="mt-2 block text-xs text-text-secondary">
                      {scope === 'all'
                        ? 'All registered business datasets available in this workspace.'
                        : 'Choose the datasets you want to include.'}
                    </span>
                  </button>
                ))}
              </div>
            </section>
            <section className="rounded-xl border border-border-color bg-background p-4 space-y-4">
              <h3 className="font-semibold">Export settings</h3>
              <div className="grid sm:grid-cols-2 gap-4">
                <label className="space-y-1 text-sm">
                  <span>Export format</span>
                  <select
                    className={field}
                    value={settings.format}
                    onChange={(e) =>
                      update({ format: e.target.value as Settings['format'] })
                    }
                  >
                    <option value="csv">CSV</option>
                    <option value="json">JSON</option>
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span>Download packaging</span>
                  <select className={field} value="zip" disabled>
                    <option value="zip">ZIP Archive · one download</option>
                  </select>
                </label>
              </div>
              <label className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={settings.include_related}
                  onChange={(e) =>
                    update({ include_related: e.target.checked })
                  }
                  className="accent-primary"
                />
                <span>
                  Include related data{' '}
                  <span className="text-text-secondary">
                    (recommended for restoration)
                  </span>
                </span>
              </label>
              <label className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={saveConfig}
                  onChange={(e) => setSaveConfig(e.target.checked)}
                  className="accent-primary"
                />
                Save export configuration
              </label>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="space-y-1 text-sm">
                  <span>Saved configuration</span>
                  <select
                    value={presetId}
                    className={field}
                    onChange={(e) => {
                      const p = presets.find((p) => p.id === e.target.value);
                      setPresetId(e.target.value);
                      setConfigName(p?.name || '');
                      if (p) setSettings(p.settings);
                    }}
                  >
                    <option value="">New configuration</option>
                    {presets.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span>Configuration name {saveConfig && '*'}</span>
                  <input
                    className={field}
                    value={configName}
                    maxLength={120}
                    onChange={(e) => setConfigName(e.target.value)}
                    placeholder="e.g. Weekly workspace backup"
                    required={saveConfig}
                  />
                </label>
              </div>
              {presetId && (
                <div className="flex gap-2">
                  <button
                    className={button}
                    disabled={busy}
                    onClick={() => withBusy(() => savePreset(true))}
                  >
                    <Copy size={14} />
                    Duplicate
                  </button>
                  <button
                    className={button}
                    disabled={busy}
                    onClick={() =>
                      withBusy(async () => {
                        await http.delete(`${base}/presets/${presetId}`);
                        setPresetId('');
                        setConfigName('');
                        await refresh();
                      })
                    }
                  >
                    <Trash2 size={14} />
                    Delete configuration
                  </button>
                </div>
              )}
            </section>
            <section className="space-y-3">
              <div className="flex flex-wrap justify-between items-center gap-2">
                <h3 className="font-semibold">
                  Datasets{' '}
                  <span className="text-sm text-text-secondary">
                    {selected.length} selected
                  </span>
                </h3>
                <div className="flex gap-3 text-xs">
                  <button
                    type="button"
                    className="text-primary"
                    onClick={() =>
                      update({
                        scope: 'custom',
                        datasets: datasets.map((d) => d.id),
                      })
                    }
                  >
                    Select All
                  </button>
                  <button
                    type="button"
                    className="text-text-secondary"
                    onClick={() =>
                      update({
                        scope: 'custom',
                        datasets: [],
                        include_related: false,
                      })
                    }
                  >
                    Clear Selection
                  </button>
                </div>
              </div>
              <div className="relative">
                <Search
                  size={16}
                  className="absolute left-3 top-3 text-text-secondary"
                />
                <input
                  aria-label="Search datasets"
                  className={`${field} pl-9`}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search datasets…"
                />
              </div>
              <div className="grid sm:grid-cols-2 gap-2 max-h-[480px] overflow-y-auto pr-1">
                {filtered.map((d) => (
                  <label
                    key={d.id}
                    className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer ${selected.some((item) => item.id === d.id) ? 'border-primary/40 bg-primary/5' : 'border-border-color bg-background'}`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 accent-primary"
                      checked={selected.some((item) => item.id === d.id)}
                      disabled={settings.scope === 'all'}
                      onChange={() => toggle(d.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex justify-between gap-2 text-sm font-medium">
                        {d.name}
                        <span className="text-xs text-text-secondary">
                          {d.count.toLocaleString()}
                        </span>
                      </span>
                      <span className="mt-1 block text-xs text-text-secondary">
                        {d.description}
                      </span>
                      {d.dependencies.length > 0 && (
                        <span className="mt-1 block text-[11px] text-text-secondary">
                          Related: {d.dependencies.join(', ')}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
              {!filtered.length && (
                <p className="text-sm text-text-secondary">
                  No datasets available.
                </p>
              )}
              {missing.length > 0 && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                  <p>
                    Missing dependencies: {missing.join(', ')}. Restoration may
                    require these records to exist.
                  </p>
                  <label className="mt-2 flex gap-2">
                    <input
                      type="checkbox"
                      checked={settings.acknowledge_dependencies}
                      onChange={(e) =>
                        update({ acknowledge_dependencies: e.target.checked })
                      }
                    />
                    I understand this selection may not be restorable on its
                    own.
                  </label>
                </div>
              )}
              {unknown.length > 0 && (
                <p role="alert" className="text-sm text-amber-500">
                  Entire Workspace is blocked until these unregistered tables
                  are reviewed: {unknown.join(', ')}.
                </p>
              )}
            </section>
          </div>
          <aside className="space-y-4">
            <section className="rounded-xl border border-primary/20 bg-background p-5 space-y-4 xl:sticky xl:top-4">
              <h3 className="flex gap-2 items-center font-semibold">
                <Archive size={18} className="text-primary" />
                Export summary
              </h3>
              <dl className="space-y-3 text-sm">
                {[
                  [
                    'Scope',
                    settings.scope === 'all'
                      ? 'Entire Workspace'
                      : 'Custom Selection',
                  ],
                  ['Datasets', String(selected.length)],
                  ['File format', settings.format.toUpperCase()],
                  ['Packaging', 'ZIP Archive'],
                  [
                    'Estimated records',
                    selected
                      .reduce((sum, d) => sum + d.count, 0)
                      .toLocaleString(),
                  ],
                  [
                    'Expected files',
                    `${selected.length + 1} (includes manifest)`,
                  ],
                  ['Timestamp', summaryTime],
                  ['Requested by', requestedBy],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-text-secondary">{label}</dt>
                    <dd className="max-w-[65%] text-right break-words">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs text-text-secondary max-h-24 overflow-auto">
                {selected.map((d) => d.name).join(', ') ||
                  'No datasets selected'}
              </p>
              <div className="border-t border-border-color pt-4 space-y-2">
                <button
                  type="button"
                  className={`${primary} w-full`}
                  onClick={generate}
                  disabled={
                    busy ||
                    exportRunning ||
                    !selected.length ||
                    (missing.length > 0 &&
                      !settings.acknowledge_dependencies) ||
                    (settings.scope === 'all' && unknown.length > 0) ||
                    (saveConfig && !configName.trim())
                  }
                >
                  {busy || exportRunning ? (
                    <LoaderCircle className="animate-spin" size={16} />
                  ) : (
                    <ArrowDownToLine size={16} />
                  )}
                  {exportRunning ? 'Export processing…' : 'Generate Export'}
                </button>
                <button
                  type="button"
                  className={`${button} w-full`}
                  disabled={busy || !configName.trim() || !selected.length}
                  onClick={() => withBusy(() => savePreset())}
                >
                  <Save size={16} />
                  Save Configuration
                </button>
                <button
                  type="button"
                  className={`${button} w-full`}
                  disabled={busy}
                  onClick={() => {
                    setSettings(initial);
                    setConfigName('');
                    setPresetId('');
                    setSaveConfig(false);
                    setMessage(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </section>
          </aside>
        </div>
      )}
      {tab === 'import' && (
        <section className="space-y-5">
          <div>
            <h3 className="font-semibold">Import / Restore</h3>
            <p className="mt-1 text-sm text-text-secondary">
              Select → Validate → Choose scope and behavior → Preview → Confirm.
              Validation changes no business records.
            </p>
          </div>
          <div className="rounded-xl border border-dashed border-primary/40 bg-primary/5 p-6 space-y-4">
            <FileUp className="text-primary" size={28} />
            <label className="block text-sm">
              Backup file · ZIP, legacy CSV or JSON · up to 32 MiB
              <input
                aria-label="Backup file"
                className="mt-2 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-primary/10 file:px-4 file:py-2 file:text-primary"
                type="file"
                accept=".zip,.csv,.json"
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setImportJob(null);
                  setPreviewCurrent(false);
                }}
              />
            </label>
            {file && (
              <p className="text-sm text-text-secondary">
                Selected file: {file.name}
              </p>
            )}
            <label className="block text-sm">
              Dataset for an individual legacy file
              <select
                value={legacyDataset}
                className={`${field} mt-1 max-w-md`}
                onChange={(e) => {
                  setLegacyDataset(e.target.value);
                  setImportJob(null);
                }}
              >
                <option value="">Detect from manifest / JSON bundle</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={primary}
              disabled={!file || busy}
              onClick={validate}
            >
              {busy && <LoaderCircle size={16} className="animate-spin" />}
              Validate backup
            </button>
          </div>
          {importJob && (
            <div className="space-y-4 rounded-xl border border-border-color p-4">
              <h4 className="font-semibold">Detected datasets</h4>
              <div className="grid sm:grid-cols-3 gap-2">
                {Object.entries(importJob.report.datasets || {}).map(
                  ([key, count]) => (
                    <label
                      key={key}
                      className="flex gap-2 rounded-lg border border-border-color p-3 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={restoreSelected.includes(key)}
                        disabled={busy || importJob.status !== 'Queued'}
                        onChange={(e) => {
                          setRestoreSelected((current) =>
                            e.target.checked
                              ? [...current, key]
                              : current.filter((v) => v !== key),
                          );
                          setPreviewCurrent(false);
                          setConfirmation('');
                        }}
                      />
                      {key}{' '}
                      <span className="ml-auto text-text-secondary">
                        {count.toLocaleString()}
                      </span>
                    </label>
                  ),
                )}
              </div>
              <label className="block max-w-md text-sm">
                Restore behavior
                <select
                  className={`${field} mt-1`}
                  value={restoreMode}
                  disabled={importJob.status !== 'Queued' || busy}
                  onChange={(e) => {
                    setRestoreMode(e.target.value as 'insert' | 'update');
                    setPreviewCurrent(false);
                    setConfirmation('');
                  }}
                >
                  <option value="insert">
                    Insert missing records · skip existing
                  </option>
                  <option value="update">
                    Insert missing and update matching identifiers
                  </option>
                </select>
              </label>
              <label className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 accent-primary"
                  checked={provisionUsers}
                  disabled={busy || importJob.status !== 'Queued'}
                  onChange={(event) => {
                    setProvisionUsers(event.target.checked);
                    setPreviewCurrent(false);
                    setConfirmation('');
                  }}
                />
                <span>
                  I authorize provisioning missing users as inactive ordinary
                  accounts. After restore, use Users to reset their passwords,
                  review their roles and activate them.
                </span>
              </label>
              <p className="text-xs text-text-secondary">
                User credentials and authorization remain managed through
                account administration. Replacement is unavailable.
              </p>
              <button
                className={button}
                disabled={
                  !restoreSelected.length ||
                  busy ||
                  importJob.status !== 'Queued'
                }
                onClick={preview}
              >
                Validate dependencies & preview impact
              </button>
              {importJob.report.warnings?.map((w) => (
                <p key={w} className="text-sm text-amber-500">
                  {w}
                </p>
              ))}
              {previewCurrent && (
                <div className="space-y-3 rounded-lg bg-background p-4">
                  <h4 className="font-medium">Restore preview</h4>
                  <div className="flex gap-6 text-sm">
                    {Object.entries(importJob.report.impact || {}).map(
                      ([key, value]) => (
                        <span key={key}>
                          {key === 'provision' ? 'inactive accounts' : key}:{' '}
                          <strong>{value}</strong>
                        </span>
                      ),
                    )}
                  </div>
                  {importJob.report.errors?.map((error) => (
                    <p
                      role="alert"
                      key={error}
                      className="text-sm text-red-400"
                    >
                      {error}
                    </p>
                  ))}
                  {importJob.report.valid && (
                    <>
                      <p className="text-sm text-text-secondary">
                        Review the impact above. Type RESTORE to explicitly
                        apply this selection in one transaction.
                      </p>
                      <input
                        aria-label="Restore confirmation"
                        className={`${field} max-w-xs`}
                        value={confirmation}
                        onChange={(e) => setConfirmation(e.target.value)}
                        placeholder="RESTORE"
                        autoComplete="off"
                      />
                      <button
                        className={`${primary} ml-2`}
                        disabled={
                          confirmation !== 'RESTORE' ||
                          busy ||
                          importJob.status !== 'Queued'
                        }
                        onClick={confirm}
                      >
                        Confirm and restore
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      )}
      {tab === 'history' && (
        <section className="space-y-4">
          {['Export', 'Import'].map((operation) => (
            <div key={operation}>
              <h3 className="mb-3 font-semibold">{operation} History</h3>
              <div className="overflow-x-auto rounded-xl border border-border-color">
                <table className="w-full text-left text-xs">
                  <thead className="bg-background text-text-secondary">
                    <tr>
                      {[
                        'Job / scope',
                        'Requested by',
                        'Started / completed',
                        'Status',
                        'Records / size',
                        'Actions / error',
                      ].map((label) => (
                        <th className="px-3 py-3 font-medium" key={label}>
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {jobs
                      .filter((job) => job.operation === operation)
                      .map((job) => (
                        <tr
                          key={job.id}
                          className="border-t border-border-color"
                        >
                          <td className="p-3">
                            <span title={job.id}>{job.id.slice(0, 8)}</span>
                            <br />
                            {job.scope}
                          </td>
                          <td className="p-3 break-all">{job.requested_by}</td>
                          <td className="p-3 whitespace-nowrap">
                            {utc(job.started_at)}
                            <br />
                            <span className="text-text-secondary">
                              {job.completed_at
                                ? utc(job.completed_at)
                                : job.operation === 'Import' &&
                                    job.status === 'Queued'
                                  ? 'Awaiting confirmation'
                                  : 'In progress'}
                            </span>
                          </td>
                          <td className="p-3">
                            <span
                              className={
                                job.status === 'Completed'
                                  ? 'text-emerald-400'
                                  : job.status === 'Failed'
                                    ? 'text-red-400'
                                    : 'text-primary'
                              }
                            >
                              {job.status}
                            </span>
                            {job.report.progress && (
                              <p className="mt-1 text-text-secondary">
                                {job.report.progress.completed_files} /{' '}
                                {job.report.progress.total_files} datasets
                              </p>
                            )}
                          </td>
                          <td className="p-3 whitespace-nowrap">
                            {job.record_count.toLocaleString()}
                            <br />
                            {(job.file_size / 1024).toFixed(1)} KiB
                          </td>
                          <td className="p-3">
                            {job.download_available && (
                              <button
                                className={button}
                                disabled={downloading === job.id}
                                onClick={() => download(job.id)}
                              >
                                <ArrowDownToLine size={14} />
                                Download ZIP
                              </button>
                            )}
                            {['Queued', 'Processing'].includes(job.status) && (
                              <button
                                className={button}
                                onClick={() =>
                                  withBusy(async () => {
                                    await http.post(
                                      `${base}/jobs/${job.id}/cancel`,
                                    );
                                    if (importJob?.id === job.id) {
                                      setImportJob(null);
                                      setPreviewCurrent(false);
                                    }
                                    await refresh();
                                  })
                                }
                                disabled={busy}
                              >
                                <X size={14} />
                                Cancel
                              </button>
                            )}
                            {job.error && (
                              <p className="mt-1 text-red-400">{job.error}</p>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                {!jobs.some((job) => job.operation === operation) && (
                  <p className="p-5 text-sm text-text-secondary">
                    No {operation.toLowerCase()} jobs yet.
                  </p>
                )}
              </div>
            </div>
          ))}
        </section>
      )}
      <details className="rounded-lg border border-border-color p-3 text-xs text-text-secondary">
        <summary className="cursor-pointer">
          Backup coverage, security & retention
        </summary>
        <ul className="mt-2 list-disc pl-5 space-y-1">
          {limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
          <li>
            Archives and import staging expire after 24 hours. Expired files are
            removed when the manager is accessed. Downloads use a one-use link
            valid for 60 seconds.
          </li>
          <li>
            CSV cells use JSON encoding for reversible UTF-8 values and
            spreadsheet formula protection. JSON is available for standard
            structured data.
          </li>
        </ul>
      </details>
    </div>
  );
}
