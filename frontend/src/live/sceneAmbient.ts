import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import { createScene } from './scene';

/**
 * The Loom of Light as a quiet background for /demo: no HUD, no labels, slower, no picking.
 * Lives in the `live-three` chunk (file name starts with "scene"), so the demo chunk stays light and three.js is
 * fetched only when the caller has already checked WebGL, reduced motion and Save-Data (see detectCapability).
 * Returns a disposer, or null when the scene could not start.
 */
export async function mountAmbient(canvas: HTMLCanvasElement, host: HTMLElement, onFail: () => void): Promise<(() => void) | null> {
  let failed = false;
  const fail = () => {
    failed = true;
    onFail();
  };
  const handle = createScene(canvas, host, { onHover: () => undefined, onLabels: () => undefined, onFail: fail, onPickMove: () => undefined }, { ambient: true });
  if (failed) return null;
  const pulse = await call(api.GET('/v1/public/pulse'));
  if (pulse.ok) {
    handle.setCases(pulse.data.replay.cases);
    handle.setScamCount(pulse.data.live.scam.blocked);
  }
  return () => handle.dispose();
}
