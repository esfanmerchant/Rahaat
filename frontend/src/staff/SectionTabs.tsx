import type { ComponentChildren, JSX } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';

/**
 * Sub-sections of a staff page as tabs: one section shows at a time, so a page needs little or no scrolling.
 *
 * - ARIA tabs pattern: Left and Right move between tabs (mirrored in RTL), Home and End jump, focus follows.
 * - The open tab is kept in the URL hash (`#section-id`), so a palette entry or a link can open a section directly.
 * - The panel slides and fades in from the side of the tab that was picked (reduced motion: no movement).
 *
 * Usage:
 *   <SectionTabs label="Case" sections={[{ id: 'brief', label: 'Briefing', icon: <svg/> }, …]}>
 *     {(id) => id === 'brief' ? <Briefing/> : <Anatomy/>}
 *   </SectionTabs>
 */
export interface Section {
  id: string;
  label: string;
  icon?: JSX.Element;
  /** A short count or state shown beside the label, e.g. "3" or "!". */
  badge?: string | number;
}

const readHash = (ids: string[]): string | null => {
  const id = typeof location !== 'undefined' ? decodeURIComponent(location.hash.replace(/^#/, '')) : '';
  return ids.includes(id) ? id : null;
};

export function SectionTabs({
  label,
  sections,
  initial,
  children,
}: {
  label: string;
  sections: Section[];
  initial?: string;
  children: (id: string) => ComponentChildren;
}) {
  const ids = sections.map((s) => s.id);
  const [active, setActive] = useState<string>(() => readHash(ids) ?? initial ?? ids[0] ?? '');
  const [direction, setDirection] = useState<1 | -1>(1);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    const onHash = () => {
      const id = readHash(ids);
      if (id) setActive(id);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [ids.join('|')]);

  const select = (id: string, focus = false) => {
    if (id === active) return;
    setDirection(ids.indexOf(id) > ids.indexOf(active) ? 1 : -1);
    setActive(id);
    history.replaceState(null, '', `${location.pathname}${location.search}#${encodeURIComponent(id)}`);
    if (focus) tabRefs.current[id]?.focus();
  };

  const onKey = (event: KeyboardEvent) => {
    const rtl = document.documentElement.dir === 'rtl';
    const i = ids.indexOf(active);
    const next = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[event.key];
    let target: string | undefined;
    if (next !== undefined) target = ids[(i + next + ids.length) % ids.length];
    if (event.key === 'Home') target = ids[0];
    if (event.key === 'End') target = ids[ids.length - 1];
    if (target) {
      event.preventDefault();
      select(target, true);
    }
  };

  return (
    <div class="st-sections">
      <div role="tablist" aria-label={label} class="st-tabs" onKeyDown={onKey}>
        {sections.map((s) => {
          const on = s.id === active;
          return (
            <button
              key={s.id}
              ref={(el) => {
                tabRefs.current[s.id] = el;
              }}
              type="button"
              role="tab"
              id={`tab-${s.id}`}
              aria-selected={on}
              aria-controls={`panel-${s.id}`}
              tabIndex={on ? 0 : -1}
              class={on ? 'st-tab st-tab-on' : 'st-tab'}
              onClick={() => select(s.id)}
            >
              {s.icon ? <span class="st-tab-icon" aria-hidden="true">{s.icon}</span> : null}
              <span>{s.label}</span>
              {s.badge !== undefined ? <span class="st-tab-badge">{s.badge}</span> : null}
            </button>
          );
        })}
      </div>
      <div
        key={active}
        role="tabpanel"
        id={`panel-${active}`}
        aria-labelledby={`tab-${active}`}
        tabIndex={0}
        class={direction > 0 ? 'st-panel st-panel-from-end' : 'st-panel st-panel-from-start'}
      >
        {children(active)}
      </div>
    </div>
  );
}
