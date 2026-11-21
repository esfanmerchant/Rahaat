import { useState } from 'preact/hooks';
import { logout } from '../shared/api/auth';
import type { AuthUser } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Pictogram } from '../shared/components/Pictogram';
import { t } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { CitizenShell } from './CitizenShell';

/** Placeholder home after login: the person's name and one primary action. */
export function HomeScreen({ user }: { user: AuthUser }) {
  const [leaving, setLeaving] = useState(false);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();

  const apply = (): void => {
    // TODO(D1.3): open the guided application (one question per screen).
  };

  const signOut = async (): Promise<void> => {
    setLeaving(true);
    await logout(); // the "/" route then shows the start screen
  };

  return (
    <CitizenShell prompt="home_apply_hint">
      <div class="flex items-center gap-4 pt-2">
        <Pictogram name="person" size={56} class="text-primary" />
        {/* display_name is rendered as text, never as HTML. */}
        <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
          {t('home_greeting', { name: user.display_name })}
        </h1>
      </div>
      <p class="text-lg text-ink-muted">{t('home_apply_hint')}</p>

      <Button size="hero" icon="document" block onClick={apply}>
        {t('home_apply')}
      </Button>

      <div class="mt-auto flex justify-center pt-6">
        <Button variant="quiet" size="md" busy={leaving} onClick={() => void signOut()}>
          {t('sign_out')}
        </Button>
      </div>
    </CitizenShell>
  );
}
