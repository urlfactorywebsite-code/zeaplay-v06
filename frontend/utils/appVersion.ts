import { version } from '../package.json';

export const APP_VERSION = version;
export const APP_VERSION_LABEL = `V${APP_VERSION}`;
export const APP_DISPLAY_NAME = `Zea.Play ${APP_VERSION_LABEL}`;

// Release-note text is persisted separately from the installed application.
// Refresh old product-version labels without rewriting authored release content.
export const releaseVersionLabel = (label?: string | null): string =>
  !label || /^(?:\d{4}\s+)?Zea\.?Play\s+v\d+(?:\.\d+){1,3}$/i.test(label.trim())
    ? APP_DISPLAY_NAME
    : label;
