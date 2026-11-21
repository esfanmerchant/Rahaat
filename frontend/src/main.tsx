import './shared/styles.css';
import { render } from 'preact';
import { App } from './App';
import { restoreSession } from './shared/api/auth';
import { loadSystemInfo } from './shared/api/system';
import { initLang } from './shared/i18n';

// Start the network work at once; it runs while the saved language loads.
void restoreSession();
void loadSystemInfo();

const root = document.getElementById('app');

void initLang().finally(() => {
  if (!root) return;
  root.textContent = ''; // drop the static boot message from index.html
  render(<App />, root);
});

// Service worker: production only, registered from bundled code (no inline script, CSP-safe).
// The generated worker calls skipWaiting and clientsClaim (vite.config.ts), so a new deploy takes over
// at once. The page then reloads once onto the new shell, but never while a text field has the focus:
// it waits until the field is left. A first install (no controller yet) never reloads.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  const sw = navigator.serviceWorker;
  let hadController = sw.controller !== null;
  let reloading = false;
  const reload = (): void => {
    const el = document.activeElement;
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.addEventListener('blur', reload, { once: true });
      return;
    }
    if (!reloading) {
      reloading = true;
      location.reload();
    }
  };
  sw.addEventListener('controllerchange', () => {
    if (hadController) reload();
    hadController = true;
  });
  void sw.register('/sw.js');
}
