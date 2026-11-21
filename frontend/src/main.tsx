import './shared/styles.css';
import { render } from 'preact';
import { registerSW } from 'virtual:pwa-register';
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

// Service worker: production only, registered from bundled code (no inline
// script, CSP-safe). autoUpdate + skipWaiting + clientsClaim reload the page
// onto a new deploy instead of serving a stale shell.
if (import.meta.env.PROD) {
  registerSW({ immediate: true });
}
