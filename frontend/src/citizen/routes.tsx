import type { ComponentChildren } from 'preact';
import { useLocation } from 'preact-iso';
import { homePathFor, isStaffRole, session } from '../shared/api/auth';
import '../shared/idle'; // lock after idle (citizens and helpers)
import { ScreenState } from '../shared/components/ScreenState';
import { lazyRoute, Redirect } from '../shared/routing';
import { vaultState } from '../shared/vault';
import { ApplyFlow } from './apply/ApplyFlow';
import { CitizenShell } from './CitizenShell';
import { HomeScreen } from './HomeScreen';
import { LoginScreen } from './LoginScreen';
import { CitizenNotFoundPage } from './NotFound';
import { ResultScreen } from './result/ResultScreen';
import { AskScreen, ProofScreen, TrackerScreen } from './result/TrackerScreen';
import { StartScreen } from './StartScreen';
import { UnlockScreen } from './UnlockScreen';

// The scam checker and the consent centre are lazy chunks: the widow's first
// screens do not wait for them. Both count in the citizen budget (check:bundle).
const ScamPages = lazyRoute<{ parts: readonly string[] }>(() => import('./scam/ScamPages'));
const MyDataPages = lazyRoute<{ parts: readonly string[] }>(() => import('./mydata/MyDataPages'));

function Restoring() {
  return (
    <CitizenShell>
      <ScreenState kind="loading" />
    </CitizenShell>
  );
}

/** "/": the start screen when signed out, the home screen when signed in. */
export function CitizenRoot() {
  const current = session.value;
  if (current.status === 'restoring') return <Restoring />;
  if (current.status === 'signed-in') {
    if (isStaffRole(current.active.role)) return <Redirect to="/staff" />;
    if (vaultState.value === 'locked') return <UnlockScreen user={current.user} />;
    return <HomeScreen user={current.user} />;
  }
  return <StartScreen />;
}

/** "/login": phone and PIN. A signed-in person goes straight to their home. */
export function CitizenLogin() {
  const current = session.value;
  if (current.status === 'restoring') return <Restoring />;
  if (current.status === 'signed-in') return <Redirect to={homePathFor(current.active.role)} />;
  return <LoginScreen />;
}

/** Citizen pages that need a signed-in citizen or helper. */
function SignedIn({ children }: { children: ComponentChildren }) {
  const current = session.value;
  if (current.status === 'restoring') return <Restoring />;
  if (current.status !== 'signed-in') return <Redirect to="/login" />;
  if (isStaffRole(current.active.role)) return <Redirect to="/staff" />;
  // Data sealed on this phone needs the PIN first (after a reload or an idle lock).
  if (vaultState.value === 'locked') return <UnlockScreen user={current.user} />;
  return <>{children}</>;
}

/** The signed-in citizen pages, matched from the path. */
function citizenPage(path: string) {
  const parts = path.replace(/\/+$/, '').split('/').filter(Boolean);
  const [first, second, ...rest] = parts;
  if (first === 'scam') return <ScamPages parts={parts.slice(1)} />;
  if (first === 'my-data') return <MyDataPages parts={parts.slice(1)} />;
  if (rest.length > 0) return null;
  if (first === 'apply') return <ApplyFlow step={second} />;
  if (second !== undefined) return null;
  switch (first) {
    case 'result':
      return <ResultScreen />;
    case 'track':
      return <TrackerScreen />;
    case 'ask':
      return <AskScreen />;
    case 'proof':
      return <ProofScreen />;
    default:
      return null;
  }
}

/**
 * The router's default route: the citizen pages (/apply/..., /result, /track,
 * /ask, /proof, /scam/..., /my-data/...), else "page not found". Keeping them
 * here leaves App.tsx alone.
 */
export function CitizenNotFound() {
  const { path } = useLocation();
  const page = citizenPage(path);
  if (page) return <SignedIn>{page}</SignedIn>;
  return <CitizenNotFoundPage />;
}
