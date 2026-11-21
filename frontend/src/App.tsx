import { LocationProvider, Route, Router } from 'preact-iso';
import { CitizenLogin, CitizenNotFound, CitizenRoot } from './citizen/routes';
import { ErrorBoundary } from './shared/components/ErrorBoundary';
import { NetworkBanner } from './shared/components/NetworkBanner';
import { lazyRoute, routeLoading } from './shared/routing';

// Separate lazy chunks (vite.config.ts manualChunks): never in the citizen budget.
const StaffApp = lazyRoute(() => import('./staff/StaffApp'));
const DemoPage = lazyRoute(() => import('./staff/demo/DemoPage'));

function RouteProgress() {
  return routeLoading.value ? (
    <div role="progressbar" aria-label="Loading" class="fixed inset-x-0 top-0 z-50 h-1 bg-primary motion-safe:animate-pulse" />
  ) : null;
}

export function App() {
  return (
    <LocationProvider>
      <NetworkBanner />
      <RouteProgress />
      <ErrorBoundary>
        <Router
          onLoadStart={() => {
            routeLoading.value = true;
          }}
          onLoadEnd={() => {
            routeLoading.value = false;
          }}
        >
          <Route path="/" component={CitizenRoot} />
          <Route path="/login" component={CitizenLogin} />
          <Route path="/staff" component={StaffApp} />
          <Route path="/staff/*" component={StaffApp} />
          <Route path="/demo" component={DemoPage} />
          <Route default component={CitizenNotFound} />
        </Router>
      </ErrorBoundary>
    </LocationProvider>
  );
}
