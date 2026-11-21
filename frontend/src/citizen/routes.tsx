import type { ComponentChildren } from 'preact';
import { useLocation } from 'preact-iso';
import { homePathFor, isStaffRole, session } from '../shared/api/auth';
import { LinkButton } from '../shared/components/Button';
import { ScreenState } from '../shared/components/ScreenState';
import { t } from '../shared/i18n';
import { Redirect } from '../shared/routing';
import { ApplyFlow } from './apply/ApplyFlow';
import { CitizenShell } from './CitizenShell';
import { HomeScreen } from './HomeScreen';
import { LoginScreen } from './LoginScreen';
import { ResultScreen } from './result/ResultScreen';
import { AskScreen, ProofScreen, TrackerScreen } from './result/TrackerScreen';
import { StartScreen } from './StartScreen';

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
  return <>{children}</>;
}

/** The signed-in citizen pages, matched from the path. */
function citizenPage(path: string) {
  const parts = path.replace(/\/+$/, '').split('/').filter(Boolean);
  const [first, second, ...rest] = parts;
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
 * /ask, /proof), else "page not found". Keeping them here leaves App.tsx alone.
 */
export function CitizenNotFound() {
  const { path } = useLocation();
  const page = citizenPage(path);
  if (page) return <SignedIn>{page}</SignedIn>;
  return (
    <CitizenShell>
      <ScreenState kind="not_found">
        <LinkButton href="/" size="lg" icon="home" block variant="secondary">
          {t('go_start')}
        </LinkButton>
      </ScreenState>
    </CitizenShell>
  );
}
