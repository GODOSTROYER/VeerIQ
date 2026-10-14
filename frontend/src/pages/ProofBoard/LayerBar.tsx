import type { Layer } from '@/api/types'
import { tint } from '@/lib/color'
import { pluralize } from '@/lib/format'
import { LAYERS } from '@/lib/layers'

export interface LayerBarProps {
  counts: Partial<Record<Layer, number>>
  /** Where the counts came from, shown under the bar. */
  source: string
}

const ORDER: Layer[] = ['armoriq', 'grant', 'domain', 'approval', 'postgres', 'runtime']

/** One stacked bar: of every action that was stopped, which layer stopped it. */
export function LayerBar({ counts, source }: LayerBarProps) {
  const rows = ORDER.map((layer) => ({ layer, n: counts[layer] ?? 0 }))
  const total = rows.reduce((a, r) => a + r.n, 0)
  if (total === 0) return null
  const summary = rows
    .filter((r) => r.n > 0)
    .map((r) => `${LAYERS[r.layer].label} ${r.n}`)
    .join(', ')

  return (
    <div>
      <div
        role="img"
        aria-label={`${total} stopped ${pluralize(total, 'action')}: ${summary}`}
        className="flex h-9 w-full gap-[3px] overflow-hidden rounded-xl"
      >
        {rows
          .filter((r) => r.n > 0)
          .map((r) => (
            <div
              key={r.layer}
              className="flex min-w-[28px] basis-0 items-center justify-center text-[13px] font-semibold text-ink-inverse"
              style={{ background: LAYERS[r.layer].color, flexGrow: r.n }}
            >
              {r.n}
            </div>
          ))}
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => {
          const Icon = LAYERS[r.layer].icon
          const color = LAYERS[r.layer].color
          return (
            <li key={r.layer} className="flex items-start gap-2.5">
              <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md" style={{ color, background: tint(color, 14) }}>
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className="min-w-0 text-[13px] leading-snug">
                <span className="font-medium text-ink">{LAYERS[r.layer].label}</span>
                <span className="tabular ml-2 text-ink-2">{r.n}</span>
              </span>
            </li>
          )
        })}
      </ul>
      <p className="mt-3 text-xs text-ink-3">{source}</p>
    </div>
  )
}
