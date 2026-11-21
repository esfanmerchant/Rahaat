import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { dial, freshId, RelayError, type RelayFailure } from './relay';

export const SERVICE_CODE = '*786#';
/** The server ends a session after 3 minutes without input (modules/ussd/menu.py). */
export const SESSION_SECONDS = 180;

export type PhoneMode = 'idle' | 'session' | 'ended';
export type InputMode = '123' | 'ABC';

/** Letters on each key, as on a feature phone. */
export const KEY_LETTERS: Record<string, string> = { '2': 'ABC', '3': 'DEF', '4': 'GHI', '5': 'JKL', '6': 'MNO', '7': 'PQRS', '8': 'TUV', '9': 'WXYZ' };
const MULTITAP_MS = 900;

export interface PhoneState {
  mode: PhoneMode;
  buffer: string;
  text: string;
  busy: boolean;
  failure: RelayFailure | null;
  notice: 'wrong_code' | null;
  inputMode: InputMode;
  /** Seconds left before the server would end the session; null outside a session. */
  secondsLeft: number | null;
  /** The key being pressed right now (for the pressed look). */
  pressed: string | null;
}

export interface PhoneApi extends PhoneState {
  press: (key: string) => void;
  letter: (char: string) => void;
  backspace: () => void;
  call: () => void;
  end: () => void;
  quickDial: () => void;
}

/**
 * One handset: dials the service code, runs the USSD session through the demo relay and keeps the `*`-joined history
 * exactly as an aggregator would. The menu itself lives on the server; this hook only types, sends and shows.
 */
export function usePhone(msisdn: string): PhoneApi {
  const [mode, setMode] = useState<PhoneMode>('idle');
  const [buffer, setBuffer] = useState('');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RelayFailure | null>(null);
  const [notice, setNotice] = useState<'wrong_code' | null>(null);
  const [inputMode, setInputMode] = useState<InputMode>('123');
  const [lastAt, setLastAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [pressed, setPressed] = useState<string | null>(null);
  const session = useRef({ id: '', history: [] as string[] });
  const tap = useRef({ key: '', index: 0, at: 0 });
  const inFlight = useRef(false);

  const reset = useCallback(() => {
    setMode('idle');
    setBuffer('');
    setText('');
    setFailure(null);
    setNotice(null);
    setInputMode('123');
    setLastAt(null);
    session.current = { id: '', history: [] };
    tap.current = { key: '', index: 0, at: 0 };
  }, []);

  useEffect(() => {
    reset();
  }, [msisdn, reset]);

  useEffect(() => {
    if (mode !== 'session') return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [mode]);

  const flash = useCallback((key: string) => {
    setPressed(key);
    window.setTimeout(() => setPressed((p) => (p === key ? null : p)), 130);
  }, []);

  const run = useCallback(
    async (history: string[], fresh: boolean) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setBusy(true);
      setFailure(null);
      try {
        const reply = await dial(session.current.id, msisdn, history.join('*'));
        session.current.history = history;
        setText(reply.text);
        setBuffer('');
        setInputMode('123');
        setLastAt(Date.now());
        setNow(Date.now());
        setMode(reply.kind === 'END' ? 'ended' : 'session');
      } catch (error) {
        setFailure(error instanceof RelayError ? error.kind : 'error');
        if (fresh) setMode('idle');
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [msisdn],
  );

  const call = useCallback(() => {
    if (inFlight.current) return;
    if (mode === 'ended') {
      reset();
      return;
    }
    if (mode === 'idle') {
      if (buffer !== SERVICE_CODE) {
        setNotice('wrong_code');
        return;
      }
      setNotice(null);
      session.current = { id: freshId('sim'), history: [] };
      void run([], true);
      return;
    }
    if (buffer === '') return;
    void run([...session.current.history, buffer], false);
  }, [mode, buffer, reset, run]);

  const quickDial = useCallback(() => {
    if (inFlight.current) return;
    setNotice(null);
    setBuffer(SERVICE_CODE);
    session.current = { id: freshId('sim'), history: [] };
    void run([], true);
  }, [run]);

  const end = useCallback(() => {
    if (mode === 'session' || mode === 'ended') {
      reset();
      return;
    }
    setBuffer('');
    setNotice(null);
    setFailure(null);
  }, [mode, reset]);

  const backspace = useCallback(() => {
    if (mode === 'ended') return;
    setBuffer((b) => b.slice(0, -1));
    tap.current = { key: '', index: 0, at: 0 };
    setNotice(null);
  }, [mode]);

  const append = useCallback((char: string) => {
    setBuffer((b) => (b.length < 24 ? b + char : b));
  }, []);

  const press = useCallback(
    (key: string) => {
      flash(key);
      if (mode === 'ended') {
        reset();
        return;
      }
      if (inFlight.current) return;
      setNotice(null);
      if (mode === 'idle') {
        append(key);
        return;
      }
      if (key === '*') return; // `*` separates the steps of the history, so it is never part of an answer
      if (key === '#') {
        setInputMode((m) => (m === '123' ? 'ABC' : '123'));
        tap.current = { key: '', index: 0, at: 0 };
        return;
      }
      if (inputMode === 'ABC' && KEY_LETTERS[key]) {
        // Multi-tap: 2, 2 quickly is B. After the letters comes the digit itself.
        const cycle = [...KEY_LETTERS[key], key];
        const t = tap.current;
        const again = t.key === key && Date.now() - t.at < MULTITAP_MS;
        const index = again ? (t.index + 1) % cycle.length : 0;
        tap.current = { key, index, at: Date.now() };
        setBuffer((b) => (again ? b.slice(0, -1) : b) + cycle[index]);
        return;
      }
      tap.current = { key: '', index: 0, at: 0 };
      append(key);
    },
    [mode, inputMode, append, flash, reset],
  );

  /** A letter or digit typed on a computer keyboard in a session. */
  const letter = useCallback(
    (char: string) => {
      if (mode !== 'session' || inFlight.current) return;
      setNotice(null);
      append(char.toUpperCase());
    },
    [mode, append],
  );

  const secondsLeft = mode === 'session' && lastAt !== null ? Math.max(0, SESSION_SECONDS - Math.floor((now - lastAt) / 1000)) : null;

  return { mode, buffer, text, busy, failure, notice, inputMode, secondsLeft, pressed, press, letter, backspace, call, end, quickDial };
}
