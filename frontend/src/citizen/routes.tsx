import type { ComponentChildren } from 'preact';
import { useLocation } from 'preact-iso';
import { acting } from '../shared/acting';
import { homePathFor, isStaffRole, session } from '../shared/api/auth';
import '../shared/idle'; // lock after idle (citizens and helpers)
import type { AuthUser } from '../shared/api/types';
import { ScreenState } from '../shared/components/ScreenState';
import { lazyRoute, Redirect } from '../shared/routing';
import { vaultState } from '../shared/vault';
import { ApplyFlow } from './apply/ApplyFlow';
import { CitizenShell } from './CitizenShell';
import { HomeScreen } from './HomeScreen';
import { LoginScreen } from './LoginScreen';
import { CitizenNotFoundPage } from './NotFound';
import { ResultScreen } from './result/ResultScreen';
import { SignupScreen } from './SignupScreen';
import { AskScreen, ProofScreen, TrackerScreen } from './result/TrackerScreen';
import { StartScreen } from './StartScreen';
import { UnlockScreen } from './UnlockScreen';

// The scam checker and the consent centre are lazy chunks: the widow's first
// screens do not wait for them. Both count in the citizen budget (check:bundle).
const ScamPages = lazyRoute<{ parts: readonly string[] }>(() => import('./scam/ScamPages'));
const MyDataPages = lazyRoute<{ parts: readonly string[] }>(() => import('./mydata/MyDataPages'));
// Helper Mode (the family list and the family PIN) and "ask about the rules" are lazy too.
const HelperFamilies = lazyRoute<{ user: AuthUser }>(() => import('./helper/HelperFamilies'));
const RulesScreen = lazyRoute<Record<string, never>>(() => import('./ask/RulesScreen'));
// Ask a person to look again, and tell us about a problem: one lazy chunk (also used by "My complaints").
const ReportPages = lazyRoute<{ view: 'appeal' | 'report' }>(() => import('./report/ReportPages'));

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
    // A helper on the shared phone first picks a family; the family's own home follows the PIN.
    if (current.active.role === 'helper' && acting.value === null) return <HelperFamilies user={current.user} />;
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
  // Every family page needs a family: a helper who has not switched yet goes to the list.
  if (current.active.role === 'helper' && acting.value === null) return <Redirect to="/" />;
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
    case 'rules':
      return <RulesScreen />;
    case 'appeal':
    case 'report':
      return <ReportPages view={first} />;
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
  // Making an account is for people who are signed out; the screen itself sends a signed-in person home.
  if (path.replace(/\/+$/, '') === '/signup') return session.value.status === 'restoring' ? <Restoring /> : <SignupScreen />;
  const page = citizenPage(path);
  if (page) return <SignedIn>{page}</SignedIn>;
  return <CitizenNotFoundPage />;
}
