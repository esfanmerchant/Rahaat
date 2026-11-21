import { homePathFor, isStaffRole, session } from '../shared/api/auth';
import { LinkButton } from '../shared/components/Button';
import { ScreenState } from '../shared/components/ScreenState';
import { t } from '../shared/i18n';
import { Redirect } from '../shared/routing';
import { CitizenShell } from './CitizenShell';
import { HomeScreen } from './HomeScreen';
import { LoginScreen } from './LoginScreen';
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

export function CitizenNotFound() {
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
