import type { ComponentChildren } from 'preact';
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { prefersReducedMotion } from './theme';

/**
 * Reorderable blocks without a library.
 *
 * - Drag by the grip (pointer events on window, so the drag survives the DOM move that a reorder causes). The dragged
 *   block lifts (scale 1.03, tilt, deeper shadow); the others glide to their new places with a FLIP animation and a
 *   spring-like curve; on drop the block settles into its slot.
 * - Keyboard: focus the grip, then arrow keys move the block one place; a polite live region says where it went.
 * - The order is saved in localStorage (guarded), keyed by `id`. resetLayouts() clears every saved order.
 *
 * The grid itself is plain CSS: pass the layout through `class` (e.g. a CSS grid). Items are keyed by id.
 */
export interface DragItem {
  id: string;
  /** Spoken name of the block, e.g. "Applications". */
  label: string;
  node: ComponentChildren;
  /** Extra class for the wrapper (for example a column span). */
  class?: string;
}

const PREFIX = 'rahat.staff.layout.';
const RESET_EVENT = 'st-dg-reset';
const SPRING = 'cubic-bezier(0.34, 1.5, 0.64, 1)';

const load = (id: string): string[] => {
  try {
    const raw = window.localStorage.getItem(PREFIX + id);
    const v: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
};
const save = (id: string, order: string[]): void => {
  try {
    window.localStorage.setItem(PREFIX + id, JSON.stringify(order));
  } catch {
    /* blocked storage: the order lasts for this page only */
  }
};

/** Forget every saved layout and tell mounted grids to go back to their default order. */
export function resetLayouts(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k?.startsWith(PREFIX)) keys.push(k);
    }
    keys.forEach((k) => window.localStorage.removeItem(k));
  } catch {
    /* nothing saved that we can reach */
  }
  window.dispatchEvent(new Event(RESET_EVENT));
}

const merge = (saved: string[], ids: string[]): string[] => [...saved.filter((s) => ids.includes(s)), ...ids.filter((i) => !saved.includes(i))].filter((v, i, a) => a.indexOf(v) === i);

interface Drag {
  id: string;
  pointerId: number;
  startX: number;
  startY: number;
  originLeft: number;
  originTop: number;
  x: number;
  y: number;
}

export function DragGrid({ id, items, class: cls = '' }: { id: string; items: DragItem[]; class?: string }) {
  const ids = items.map((i) => i.id);
  const [order, setOrder] = useState<string[]>(() => merge(load(id), ids));
  const [note, setNote] = useState('');
  const els = useRef<Record<string, HTMLElement | null>>({});
  const grips = useRef<Record<string, HTMLButtonElement | null>>({});
  const before = useRef<Record<string, DOMRect> | null>(null);
  const drag = useRef<Drag | null>(null);
  const refocus = useRef<string | null>(null);
  const orderRef = useRef(order);
  orderRef.current = order;
  const moveRef = useRef<(e: PointerEvent) => void>(() => undefined);
  const upRef = useRef<(e: PointerEvent) => void>(() => undefined);
  const stableMove = useRef((e: PointerEvent) => moveRef.current(e)).current;
  const stableUp = useRef((e: PointerEvent) => upRef.current(e)).current;

  const current = merge(order, ids);
  const byId = new Map(items.map((i) => [i.id, i]));

  const snapshot = (): void => {
    const r: Record<string, DOMRect> = {};
    for (const k of Object.keys(els.current)) {
      const el = els.current[k];
      if (el) r[k] = el.getBoundingClientRect();
    }
    before.current = r;
  };

  /** Put the dragged block under the pointer: measure its layout slot without the transform, then offset from there. */
  const place = (): void => {
    const d = drag.current;
    const el = d ? els.current[d.id] : null;
    if (!d || !el) return;
    el.style.transform = 'none';
    const base = el.getBoundingClientRect();
    const dx = d.originLeft + (d.x - d.startX) - base.left;
    const dy = d.originTop + (d.y - d.startY) - base.top;
    el.style.transform = `translate(${dx}px, ${dy}px) scale(1.03) rotate(1.2deg)`;
  };

  const commit = (next: string[]): void => {
    snapshot();
    setOrder(next);
    save(id, next);
  };

  useLayoutEffect(() => {
    const prev = before.current;
    before.current = null;
    if (drag.current) place();
    if (refocus.current) {
      grips.current[refocus.current]?.focus();
      refocus.current = null;
    }
    if (!prev || prefersReducedMotion()) return;
    for (const k of Object.keys(els.current)) {
      const el = els.current[k];
      const a = prev[k];
      if (!el || !a || k === drag.current?.id) continue;
      const b = el.getBoundingClientRect();
      const dx = a.left - b.left;
      const dy = a.top - b.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 460, easing: SPRING });
    }
  }, [current.join('|')]);

  useEffect(() => {
    const onReset = () => {
      snapshot();
      setOrder(ids);
    };
    window.addEventListener(RESET_EVENT, onReset);
    return () => window.removeEventListener(RESET_EVENT, onReset);
  }, [ids.join('|')]);

  const endDrag = (): void => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    window.removeEventListener('pointermove', stableMove);
    window.removeEventListener('pointerup', stableUp);
    window.removeEventListener('pointercancel', stableUp);
    const el = els.current[d.id];
    if (!el) return;
    const from = el.style.transform;
    const done = () => {
      el.style.transform = '';
      el.classList.remove('is-lifted');
    };
    if (prefersReducedMotion() || !from) return done();
    el.style.transform = '';
    const settle = el.animate([{ transform: from }, { transform: 'none' }], { duration: 520, easing: SPRING });
    settle.onfinish = done;
    settle.oncancel = done;
  };

  function onMove(e: PointerEvent): void {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointerId) return;
    d.x = e.clientX;
    d.y = e.clientY;
    place();
    // Which other block is the pointer over? Move the dragged one to that place.
    const list = merge(orderRef.current, ids);
    const over = list.find((k) => {
      if (k === d.id) return false;
      const r = els.current[k]?.getBoundingClientRect();
      return Boolean(r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom);
    });
    if (over) {
      const next = list.filter((k) => k !== d.id);
      next.splice(list.indexOf(over), 0, d.id);
      if (next.join('|') !== list.join('|')) commit(next);
    }
  }
  function onUp(e: PointerEvent): void {
    if (drag.current && e.pointerId === drag.current.pointerId) endDrag();
  }

  moveRef.current = onMove;
  upRef.current = onUp;
  useEffect(() => () => endDrag(), []);

  const onGripDown = (e: PointerEvent, itemId: string): void => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    const el = els.current[itemId];
    if (!el) return;
    e.preventDefault();
    const r = el.getBoundingClientRect();
    drag.current = { id: itemId, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, originLeft: r.left, originTop: r.top, x: e.clientX, y: e.clientY };
    el.getAnimations().forEach((a) => a.cancel());
    el.classList.add('is-lifted');
    place();
    window.addEventListener('pointermove', stableMove);
    window.addEventListener('pointerup', stableUp);
    window.addEventListener('pointercancel', stableUp);
  };

  const onGripKey = (e: KeyboardEvent, itemId: string): void => {
    const step = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : 0;
    if (!step) return;
    e.preventDefault();
    const i = current.indexOf(itemId);
    const j = Math.max(0, Math.min(current.length - 1, i + step));
    if (i === j) return;
    const next = [...current];
    next.splice(i, 1);
    next.splice(j, 0, itemId);
    refocus.current = itemId;
    commit(next);
    setNote(`${byId.get(itemId)?.label ?? 'Block'} moved to place ${j + 1} of ${next.length}`);
  };

  return (
    <div class={cls}>
      {current.map((k) => {
        const item = byId.get(k);
        if (!item) return null;
        return (
          <div
            key={k}
            ref={(el) => {
              els.current[k] = el;
            }}
            class={`dg-item ${item.class ?? ''}`}
            data-dg-id={k}
          >
            {item.node}
            <button
              type="button"
              class="dg-grip"
              ref={(el) => {
                grips.current[k] = el;
              }}
              aria-label={`Move ${item.label}. Drag, or use the arrow keys.`}
              title="Drag to move"
              onPointerDown={(e) => onGripDown(e, k)}
              onKeyDown={(e) => onGripKey(e, k)}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                <circle cx="4.5" cy="3" r="1.2" />
                <circle cx="9.5" cy="3" r="1.2" />
                <circle cx="4.5" cy="7" r="1.2" />
                <circle cx="9.5" cy="7" r="1.2" />
                <circle cx="4.5" cy="11" r="1.2" />
                <circle cx="9.5" cy="11" r="1.2" />
              </svg>
            </button>
          </div>
        );
      })}
      <span class="sr-only" role="status" aria-live="polite">
        {note}
      </span>
    </div>
  );
}
