import { useEffect, useState } from 'preact/hooks';
import { audioKeys, type SpeechItem } from './audio';
import type { Speech } from './components/AudioPrompt';
import type { Lang } from './i18n';

interface ServerSpeechInput {
  /** Changes whenever the content changes, so auto-play runs again. */
  id: string;
  /** Language of the server's sentences and clips. */
  lang: Lang;
  /** Pre-generated clips the server named (`audio_keys`), in order. */
  clips: readonly string[];
  /** The same sentences as text, read by a device voice when a clip is missing. */
  lines: readonly string[];
  /** Our own clips before and after, in the UI language. */
  before?: readonly SpeechItem[];
  after?: readonly SpeechItem[];
  /** Language of `before` and `after`. */
  uiLang: Lang;
}

/**
 * Speech for server sentences: the server's recordings when every one of them
 * exists, otherwise its sentences read by a device voice (never Urdu with an
 * English voice). `undefined` while the list of recordings loads.
 */
export function useServerSpeech(input: ServerSpeechInput | null): Speech | undefined {
  const spoken = input?.lang;
  const [files, setFiles] = useState<{ lang: Lang; keys: Set<string> | null } | undefined>(undefined);
  useEffect(() => {
    if (!spoken) return undefined;
    let live = true;
    void audioKeys(spoken).then((keys) => {
      if (live) setFiles({ lang: spoken, keys });
    });
    return () => {
      live = false;
    };
  }, [spoken]);
  if (!input || !files || files.lang !== input.lang) return undefined;
  const allRecorded = input.clips.length > 0 && files.keys !== null && input.clips.every((key) => files.keys?.has(key));
  const middle: SpeechItem[] = allRecorded
    ? input.clips.map((key) => ({ key, lang: input.lang }))
    : input.lines.filter(Boolean).map((text, index) => ({ key: `server.${index}`, text, lang: input.lang }));
  return {
    id: `${input.id}:${allRecorded ? 'files' : 'voice'}`,
    items: [...(input.before ?? []), ...middle, ...(input.after ?? [])],
    lang: input.uiLang,
  };
}
