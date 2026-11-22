import { useCallback, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { playPrompt } from '../shared/audio';
import { loginNotice, logout } from '../shared/api/auth';
import type { AuthUser } from '../shared/api/types';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Button } from '../shared/components/Button';
import { Pictogram } from '../shared/components/Pictogram';
import { lang, t, type MessageKey } from '../shared/i18n';
import { useFocusOnMount } from '../shared/useFocusOnMount';
import { forgetVaultState, lockReason, unlock } from '../shared/vault';
import { CitizenShell } from './CitizenShell';
import { Keypad, PinDots } from './Keypad';
import { PIN_MAX, PIN_MIN } from './phone';

/**
 * The PIN opens this person's data sealed on the phone: after a reload (the
 * key never survives one) or after the app locked itself when nobody used it.
 * PIN digits are never spoken. Five wrong PINs delete the sealed data.
 */
export function UnlockScreen({ user }: { user: AuthUser }) {
  const { route } = useLocation();
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(lockReason.peek() === 'idle' ? 'unlock_idle' : null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const code = lang.value;

  const say = (key: MessageKey): void => {
    setNotice(key);
    playPrompt(key, code, t(key, undefined, code));
  };

  const onDigit = useCallback(
    (digit: string) => {
      if (busy) return;
      setPin((value) => (value.length < PIN_MAX ? value + digit : value));
    },
    [busy],
  );
  const onDelete = useCallback(() => {
    if (!busy) setPin((value) => value.slice(0, -1));
  }, [busy]);

  const onDone = useCallback(() => {
    if (pin.length < PIN_MIN) {
      say('login_pin_too_short');
      return;
    }
    setBusy(true);
    void unlock(user.id, pin).then(async (outcome) => {
      setBusy(false);
      setPin('');
      if (outcome === 'ok') return; // the gate opens by itself
      if (outcome === 'none') {
        forgetVaultState();
        return;
      }
      if (outcome === 'wrong') {
        say('unlock_wrong');
        return;
      }
      loginNotice.value = 'unlock_wiped';
      await logout();
      route('/login', true); // the sign-in screen says what happened
    });
  }, [pin, user.id, code]);

  // Someone else has the phone: sign out, but keep the sealed data for its owner.
  const notMe = (): void => {
    setBusy(true);
    void logout({ keepVault: true });
  };

  return (
    <CitizenShell prompt="unlock_hint">
      <div class="flex items-center gap-4">
        <Pictogram name="lock" size={56} class="text-primary" />
        <div class="flex flex-col">
          {/* display_name is rendered as text, never as HTML. */}
          <p class="text-lg text-ink-muted">{t('home_greeting', { name: user.display_name })}</p>
          <h1 ref={headingRef} tabIndex={-1} class="text-2xl font-bold">
            {t('unlock_title')}
          </h1>
        </div>
      </div>
      <p class="text-lg text-ink-muted">{t('unlock_hint')}</p>
      <PinDots count={pin.length} />
      {notice ? (
        <div role="alert" class="flex items-start gap-3 rounded-lg border-2 border-warning bg-warning-soft p-3 text-warning-ink">
          <Pictogram name={notice === 'unlock_idle' ? 'clock' : 'warning'} size={32} />
          <div class="flex flex-1 flex-col items-start gap-2">
            <p class="text-lg font-semibold">{t(notice)}</p>
            <AudioPrompt prompt={notice} />
          </div>
        </div>
      ) : null}
      <Keypad onDigit={onDigit} onDelete={onDelete} onDone={onDone} doneEnabled={pin.length >= PIN_MIN} disabled={busy} busy={busy} />
      <Button size="md" variant="quiet" icon="person" block disabled={busy} onClick={notMe}>
        {t('unlock_not_me')}
      </Button>
    </CitizenShell>
  );
}
