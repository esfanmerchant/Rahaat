import { computed, signal } from '@preact/signals';
import { api } from './client';
import { call } from './problem';
import type { SystemInfo } from './types';

/** Public system info (GET /v1/system/info), loaded once at startup. */
export const systemInfo = signal<SystemInfo | null>(null);

let loading: Promise<void> | null = null;

export function loadSystemInfo(): Promise<void> {
  if (!loading) {
    loading = call(api.GET('/v1/system/info')).then((result) => {
      if (result.ok) systemInfo.value = result.data;
      else loading = null; // allow a later retry
    });
  }
  return loading;
}

export const demoMode = computed(() => systemInfo.value?.demo_mode === true);

/**
 * Server-controlled feature flag. A feature that is not demo-proof stays off
 * (CLAUDE.md priority 3). Unknown flags are off.
 */
export function featureOn(name: string): boolean {
  return systemInfo.value?.features[name] === true;
}
