import { useFocusOnMount } from '../shared/useFocusOnMount';
import type { NavItem } from './nav';

/**
 * DEV PLACEHOLDER. Replace with the real page for the work item. Pages that
 * are still placeholders are hidden by building with VITE_SHOW_UNBUILT=false.
 */
export function PlaceholderPage({ item }: { item: NavItem }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  return (
    <section aria-labelledby="page-title" class="flex max-w-3xl flex-col gap-3">
      <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
        {item.label}
      </h1>
      <div class="rounded-sm border-2 border-dashed border-warning-ink bg-warning-soft p-4 text-warning-ink">
        <p class="font-mono text-xs font-bold uppercase tracking-wide">Dev placeholder</p>
        <p class="mt-1 text-base font-semibold">Not built yet</p>
        <dl class="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 font-mono text-xs">
          <dt>Route</dt>
          <dd>/staff/{item.slug}</dd>
          <dt>Work item</dt>
          <dd>PLAN {item.workItem}</dd>
          <dt>Owner</dt>
          <dd>Track D2, frontend/src/staff</dd>
        </dl>
      </div>
    </section>
  );
}
