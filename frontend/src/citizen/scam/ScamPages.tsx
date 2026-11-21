import { CitizenNotFoundPage } from '../NotFound';
import { ScamAnswerScreen, ScamAskScreen } from './ScamAnswerScreen';
import { ScamCheckScreen } from './ScamCheckScreen';
import { ScamHistoryScreen } from './ScamHistoryScreen';

/**
 * /scam, /scam/history, /scam/answer/{id} and /scam/answer/{id}/ask. A lazy
 * chunk: the shopkeeper downloads it the first time, the service worker keeps it.
 */
export default function ScamPages({ parts }: { parts: readonly string[] }) {
  const [first, id, last, ...extra] = parts;
  if (extra.length > 0) return <CitizenNotFoundPage />;
  if (first === undefined) return <ScamCheckScreen />;
  if (first === 'history' && id === undefined) return <ScamHistoryScreen />;
  if (first === 'answer' && id && /^[0-9a-f-]{36}$/i.test(id)) {
    if (last === undefined) return <ScamAnswerScreen key={id} id={id} />;
    if (last === 'ask') return <ScamAskScreen key={id} id={id} />;
  }
  return <CitizenNotFoundPage />;
}
