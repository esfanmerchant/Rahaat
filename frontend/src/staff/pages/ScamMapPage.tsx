import { Fragment } from 'preact';
import { useEffect, useMemo, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN } from '../kit';
import { activeRole, ALL_DISTRICTS, labelText, PUNJAB_TILES, SINDH_TILES, type CampaignOut, type MapOut } from '../scam';
import { Spark, TileGrid, TileLegend, TrendChart } from '../ScamCharts';
import { Badge, fmtTime, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';
import { emptyDraft, WarningForm, WarningList, type WarningDraft } from './WarningsPanel';

const WINDOWS = [7, 14, 30, 90] as const;
const REFRESH_MS = 30_000;

/**
 * The Scam Map: reports by district, type and day built from classified messages. The server hides any
 * group of fewer than 5 reports; this page says so instead of showing a zero.
 */
export function ScamMapPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = activeRole();
  const canWarn = role === 'officer' || role === 'admin';
  const [days, setDays] = useState<number>(14);
  const [type, setType] = useState<string>('scam');
  const [live, setLive] = useState(true);
  const [tick, setTick] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<WarningDraft | null>(null);
  const [warnKey, setWarnKey] = useState(0);

  const kind = type === 'all' ? 'all' : 'scam';
  const only = type === 'scam' || type === 'all' ? null : type;

  const [map, reloadMap] = useLoad(() => call(api.GET('/v1/scam/map', { params: { query: { days, kind } } })), [days, kind, tick]);
  const [trends, reloadTrends] = useLoad(() => call(api.GET('/v1/scam/trends', { params: { query: { days, kind } } })), [days, kind, tick]);
  const [camps, reloadCamps] = useLoad(() => call(api.GET('/v1/scam/campaigns', { params: { query: { days, limit: 20 } } })), [days, tick]);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [live]);
  useEffect(() => {
    if (map.state === 'ok') setUpdated(new Date());
  }, [map]);

  const refreshAll = () => {
    reloadMap();
    reloadTrends();
    reloadCamps();
  };

  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Scam Map
        </h1>
        <label class="flex items-center gap-1">
          Type
          <select class={INPUT} value={type} onChange={(e) => setType(e.currentTarget.value)}>
            <option value="scam">All scam types</option>
            {(map.state === 'ok' ? map.data.labels : ['relief_scam', 'phishing_link', 'advance_fee', 'impersonation']).map((l) => (
              <option key={l} value={l}>
                {labelText(l)}
              </option>
            ))}
            <option value="all">Every checked message (includes genuine)</option>
          </select>
        </label>
        <label class="flex items-center gap-1">
          Window
          <select class={INPUT} value={String(days)} onChange={(e) => setDays(Number(e.currentTarget.value))}>
            {WINDOWS.map((d) => (
              <option key={d} value={d}>
                last {d} days
              </option>
            ))}
          </select>
        </label>
        <button type="button" class={BTN} onClick={refreshAll}>
          Refresh
        </button>
        <label class="flex items-center gap-1">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.currentTarget.checked)} />
          Live (every 30 s)
        </label>
        <span class="text-xs text-ink-subtle" role="status">
          {updated ? `Updated ${updated.toLocaleTimeString('en-GB')}` : 'Not loaded yet'}
        </span>
        {canWarn ? (
          <button type="button" class={`${BTN} ms-auto`} onClick={() => setDraft({ ...emptyDraft })}>
            New warning
          </button>
        ) : null}
      </div>

      {draft && canWarn ? <WarningForm draft={draft} onChange={setDraft} onPublished={() => setWarnKey((n) => n + 1)} onClose={() => setDraft(null)} /> : null}

      <div class="grid gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Section id="map" title="Districts">
          {map.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the map…" /> : null}
          {map.state === 'fail' ? <FailureState failure={map.failure} density="staff" heading="h2" onRetry={reloadMap} /> : null}
          {map.state === 'ok' ? (
            <MapBody
              map={map.data}
              only={only}
              selected={selected}
              onSelect={(d) => setSelected((cur) => (cur === d ? null : d))}
              canWarn={canWarn}
              onWarn={(d) =>
                setDraft({ ...emptyDraft, district: d, about: `${d} district`, title: `Scam warning for ${d}` })
              }
            />
          ) : null}
        </Section>

        <Section id="trends" title="Reports per day">
          {trends.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading trends…" /> : null}
          {trends.state === 'fail' ? <FailureState failure={trends.failure} density="staff" heading="h2" onRetry={reloadTrends} /> : null}
          {trends.state === 'ok' ? (
            <div class="flex flex-col gap-2">
              <TrendChart trends={trends.data} only={only} />
              <p class="text-xs text-ink-subtle">{trends.data.note}</p>
            </div>
          ) : null}
        </Section>
      </div>

      <Section id="campaigns" title="Campaigns (the same message, many reports)">
        {camps.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading campaigns…" /> : null}
        {camps.state === 'fail' ? <FailureState failure={camps.failure} density="staff" heading="h2" onRetry={reloadCamps} /> : null}
        {camps.state === 'ok' ? (
          <CampaignTable
            items={camps.data.items.filter((c) => only === null || c.label === only)}
            hidden={camps.data.hidden}
            note={camps.data.note}
            canWarn={canWarn}
            onWarn={(c) =>
              setDraft({
                title: `Scam warning: ${labelText(c.label).toLowerCase()}`,
                body_en: '',
                district: c.districts[0]?.district ?? '',
                cluster_id: c.id,
                about: `campaign of ${c.size_in_window} reports (${labelText(c.label)})`,
              })
            }
          />
        ) : null}
      </Section>

      <WarningList reloadKey={warnKey} canWithdraw={canWarn} />
    </section>
  );
}

function MapBody({ map, only, selected, onSelect, canWarn, onWarn }: { map: MapOut; only: string | null; selected: string | null; onSelect: (d: string) => void; canWarn: boolean; onWarn: (d: string) => void }) {
  const { counts, max } = useMemo(() => {
    const m = new Map<string, number>();
    if (only === null) for (const r of map.district_totals) m.set(r.district, r.count);
    else for (const r of map.districts) if (r.label === only) m.set(r.district, (m.get(r.district) ?? 0) + r.count);
    return { counts: m, max: Math.max(0, ...m.values()) };
  }, [map, only]);
  const hiddenGroups = map.hidden.districts ?? 0;
  const known = useMemo(() => new Set(ALL_DISTRICTS), []);
  const unplaced = [...counts.keys()].filter((d) => !known.has(d));
  const perType = selected ? map.districts.filter((r) => r.district === selected) : [];
  const shown = [...counts.values()].reduce((a, b) => a + b, 0);
  return (
    <div class="flex flex-col gap-3">
      <p class="text-sm">
        <span class="font-semibold tabular-nums">{shown}</span> reports are visible in {map.first_day} to {map.last_day} ({map.timezone}).{' '}
        {hiddenGroups > 0 ? <span>{hiddenGroups} district-and-type groups have fewer than {map.k} reports and are hidden, so every number here is a lower bound.</span> : null}
      </p>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <TileGrid id="sd" title="Sindh" rows={SINDH_TILES} counts={counts} max={max} hiddenGroups={hiddenGroups} selected={selected} onSelect={onSelect} />
        <TileGrid id="pb" title="Punjab" rows={PUNJAB_TILES} counts={counts} max={max} hiddenGroups={hiddenGroups} selected={selected} onSelect={onSelect} />
      </div>
      {unplaced.length ? <p class="text-xs text-ink-muted">Not on the tile map: {unplaced.map((d) => `${d} (${counts.get(d)})`).join(', ')}</p> : null}
      <TileLegend max={max} hiddenGroups={hiddenGroups} />
      <div class="border border-line p-2" aria-live="polite">
        {selected ? (
          <div class="flex flex-col gap-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="font-semibold">{selected}</h3>
              <span class="tabular-nums">{counts.get(selected) ?? 0} visible</span>
              {canWarn ? (
                <button type="button" class={`${BTN} ms-auto`} onClick={() => onWarn(selected)}>
                  Warn about {selected}
                </button>
              ) : null}
            </div>
            {perType.length === 0 ? (
              <p class="text-ink-muted">No type has {map.k} or more reports here, so nothing can be shown without risking identifying someone.</p>
            ) : (
              <ul class="flex flex-wrap gap-x-4">
                {perType.map((r) => (
                  <li key={r.label}>
                    {labelText(r.label)} <span class="font-mono tabular-nums">{r.count}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p class="text-ink-subtle">Select a district tile (Enter or click) to see its types and publish a warning for it.</p>
        )}
      </div>
      <p class="text-xs text-ink-subtle">{map.note}</p>
    </div>
  );
}

function CampaignTable({ items, hidden, note, canWarn, onWarn }: { items: CampaignOut[]; hidden: number; note: string; canWarn: boolean; onWarn: (c: CampaignOut) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) {
    return (
      <p class="text-ink-muted">
        No campaign of 5 or more similar reports in this window{hidden > 0 ? ` (${hidden} smaller groups hidden)` : ''}. {note}
      </p>
    );
  }
  return (
    <div class="flex flex-col gap-2">
      <div class="overflow-x-auto border border-line">
        <table class="w-full border-collapse text-sm">
          <caption class="sr-only">Campaigns, largest first</caption>
          <thead>
            <tr>
              <Th>Type</Th>
              <Th>Sample (redacted)</Th>
              <Th>Reports</Th>
              <Th>In window</Th>
              <Th>Districts</Th>
              <Th>First seen</Th>
              <Th>Last seen</Th>
              <Th>Links</Th>
              <Th>Senders</Th>
              <Th>Open</Th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <Fragment key={c.id}>
                <tr class="hover:bg-sunken">
                  <td class={TD}>
                    <Badge tone="bad">{labelText(c.label)}</Badge>
                  </td>
                  <td class={`${TD} max-w-sm`}>{c.sample_text}</td>
                  <td class={`${TD} tabular-nums`}>{c.size}</td>
                  <td class={`${TD} tabular-nums`}>{c.size_in_window}</td>
                  <td class={TD}>{c.districts.map((d) => `${d.district} ${d.count}`).join(', ') || <span class="text-ink-subtle">hidden (under 5 each)</span>}</td>
                  <td class={`${TD} font-mono text-xs`}>{fmtTime(c.first_seen)}</td>
                  <td class={`${TD} font-mono text-xs`}>{fmtTime(c.last_seen)}</td>
                  <td class={TD}>{c.hosts.length ? c.hosts.map((h) => <div key={h}><Mono>{h}</Mono></div>) : <span class="text-ink-subtle">none</span>}</td>
                  <td class={`${TD} tabular-nums`}>{c.senders}</td>
                  <td class={TD}>
                    <button type="button" class="underline" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
                      {open === c.id ? 'Close' : 'Open'}
                    </button>
                  </td>
                </tr>
                {open === c.id ? (
                  <tr>
                    <td colSpan={10} class="border-b border-line bg-sunken p-3">
                      <div class="flex flex-wrap items-start gap-6">
                        <div>
                          <div class="text-xs font-semibold uppercase text-ink-muted">Daily reports</div>
                          <Spark points={c.trend} />
                        </div>
                        <div class="min-w-64 flex-1">
                          <div class="text-xs font-semibold uppercase text-ink-muted">Message (redacted, shown as text)</div>
                          <p class="whitespace-pre-wrap">{c.sample_text}</p>
                          <p class="mt-1 font-mono text-xs text-ink-subtle break-all">signature {c.signature}</p>
                        </div>
                        {canWarn ? (
                          <button type="button" class={BTN} onClick={() => onWarn(c)}>
                            Warn about this campaign
                          </button>
                        ) : null}
                        <a class="underline" href={`/staff/scam-reports?cluster=${c.id}`}>
                          See its reports
                        </a>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p class="text-xs text-ink-subtle">
        {hidden > 0 ? `${hidden} smaller groups are hidden. ` : ''}
        {note}
      </p>
    </div>
  );
}
