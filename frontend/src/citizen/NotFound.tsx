import { LinkButton } from '../shared/components/Button';
import { ScreenState } from '../shared/components/ScreenState';
import { t } from '../shared/i18n';
import { CitizenShell } from './CitizenShell';

/** "Page not found", with the way back to the start. */
export function CitizenNotFoundPage() {
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
