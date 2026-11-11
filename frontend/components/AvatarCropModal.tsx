import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';
import React, { useCallback, useEffect, useState } from 'react';
import Cropper, { Area } from 'react-easy-crop';
import { AvatarCropMetadata } from '../types';
import { getCroppedImageDataUrl } from '../utils/image';

interface AvatarCropModalProps {
  isOpen: boolean;
  imageSrc: string | null;
  title?: string;
  onCancel: () => void;
  onComplete?: (dataUrl: string) => void;
  onCompleteWithMetadata?: (metadata: AvatarCropMetadata) => Promise<void> | void;
  aspect?: number;
  uploadProgress?: number;
}

const AvatarCropModal: React.FC<AvatarCropModalProps> = ({
  isOpen,
  imageSrc,
  title = 'Adjust avatar',
  onCancel,
  onComplete,
  onCompleteWithMetadata,
  aspect = 1,
  uploadProgress,
}) => {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rotation = 0;
  useEffect(() => { setCrop({ x: 0, y: 0 }); setZoom(1); setCroppedAreaPixels(null); setError(null); }, [imageSrc]);

  const handleCropComplete = useCallback((_croppedArea: Area, croppedPixels: Area) => {
    setCroppedAreaPixels(croppedPixels);
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!imageSrc || !croppedAreaPixels) {
      setError('Unable to crop image. Please try again.');
      return;
    }

    try {
      setError(null);
      setIsSaving(true);
      if (onCompleteWithMetadata) {
        const metadata: AvatarCropMetadata = {
          x: croppedAreaPixels.x,
          y: croppedAreaPixels.y,
          width: croppedAreaPixels.width,
          height: croppedAreaPixels.height,
          scale: zoom,
          rotate: rotation,
        };
        await onCompleteWithMetadata(metadata);
      }
      if (onComplete) {
        const cropped = await getCroppedImageDataUrl(imageSrc, croppedAreaPixels);
        await onComplete(cropped);
      }
    } catch (cropError) {
      setError(cropError instanceof Error ? cropError.message : 'Failed to crop image');
    } finally {
      setIsSaving(false);
    }
  }, [croppedAreaPixels, imageSrc, onComplete, onCompleteWithMetadata, rotation, zoom]);

  if (!isOpen || !imageSrc) {
    return null;
  }

  return (
    <Dialog open={isOpen} onClose={isSaving ? () => {} : onCancel} className="fixed inset-0 z-[90]">
    <div className="fixed inset-0 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <DialogPanel className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <DialogTitle className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</DialogTitle>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSaving}
            className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="Close cropper"
          >
            ✕
          </button>
        </div>

        <div className="relative h-[360px] w-full bg-slate-900/80 dark:bg-slate-800">
          <Cropper
            image={imageSrc}
            crop={crop}
            zoom={zoom}
            aspect={aspect}
            cropShape="round"
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={handleCropComplete}
            showGrid={false}
            restrictPosition
          />
        </div>

        <div className="flex flex-wrap gap-4 items-center justify-between border-t border-slate-200 px-6 py-4 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              Zoom
            </label>
            <input
              type="range"
              aria-label="Avatar zoom"
              min={1}
              max={3}
              step={0.1}
              value={zoom}
              onChange={(event) => setZoom(Number(event.target.value))}
              className="w-44 accent-indigo-500 dark:accent-indigo-400"
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onCancel}
            disabled={isSaving}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isSaving}
              onClick={handleConfirm}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:opacity-50"
            >
              {isSaving ? 'Saving…' : 'Save avatar'}
            </button>
          </div>
        </div>

        {isSaving && uploadProgress !== undefined && <div className="px-6 pb-3" role="status" aria-live="polite">
          <p className="mb-1 text-sm text-slate-400">{uploadProgress < 100 ? `Uploading ${Math.round(uploadProgress)}%` : 'Processing image?'}</p>
          <progress aria-label="Avatar upload progress" value={uploadProgress} max={100} className="w-full" />
        </div>}
        {error && (
          <div className="border-t border-rose-200 bg-rose-50 px-6 py-3 text-sm font-medium text-rose-600 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
            {error}
          </div>
        )}
      </DialogPanel>
    </div>
    </Dialog>
  );
};

export default AvatarCropModal;
