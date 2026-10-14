import type { Layer, VerificationResult } from '@/api/types'
import { Badge, Disclosure, LayerChip } from '@/components/ui'
import { Technical } from '@/lib/detail'
import { formatDuration, titleCase } from '@/lib/format'
import { LAYERS } from '@/lib/layers'
import { GROUPS, groupOf } from './groups'

export function isLayer(v: unknown): v is Layer { return typeof v === 'string' && v in LAYERS }
function layerName(value: string | null): string {
  if (value?.includes(' or ')) return value.split(' or ').map(layerName).join(' or ')
  return value && isLayer(value) ? LAYERS[value].label : value ? titleCase(value) : 'Not recorded'
}
function LayerOrText({ value }: { value: string | null }) {
  return value && isLayer(value) ? <LayerChip layer={value} compact /> : <Badge>{value ? titleCase(value) : 'Not recorded'}</Badge>
}
/** Describe observations, never infer an unchanged database from a passing badge. */
function evidenceSentences(e: Record<string, unknown>): string[] {
  const sentences: string[] = []
  if (typeof e.handler_entries === 'number') sentences.push(`The protected handler ran ${e.handler_entries} times.`)
  if (typeof e.apply_handler_entries === 'number') sentences.push(`The repair handler ran ${e.apply_handler_entries} times.`)
  if (e.restore_in_signed_plan === false) sentences.push('Restoring access was outside the signed plan.')
  if (e.ag77_status === 'revoked') sentences.push('The account stayed revoked. Nothing changed in its access.')
  if (e.orders_unchanged === true || e.unchanged_after_substitution === true || e['O-2046_unchanged'] === true) sentences.push('The checked orders did not change.')
  if (e.beacon_checksum_unchanged === true) sentences.push('The other tenant’s data stayed unchanged.')
  if (typeof e.manifests_created === 'number') sentences.push(`${e.manifests_created} repair proposals were stored.`)
  const counts = e.rows_updated
  if (counts && typeof counts === 'object' && 'rows_updated' in counts && typeof counts.rows_updated === 'number') sentences.push(`${counts.rows_updated} orders were updated by the permitted repair.`)
  if (e.ag77_before === 'revoked' && e.ag77_after_operator_call === 'active') sentences.push('The operator’s control call restored access; the recorded fixture reset revoked it again.')
  if (e.repair_intact === true) sentences.push('The committed repair stayed intact despite the reporting failure.')
  if (e.simulated_enforcement === true) sentences.push('This check used simulated enforcement.')
  return sentences
}
function ResultRow({ result: r }: { result: VerificationResult }) {
  const actual = r.layer_actual === null ? null : String(r.layer_actual)
  const mismatch = actual !== null && !String(r.layer_expected).split(' or ').includes(actual)
  const evidence = evidenceSentences(r.evidence ?? {})
  return <li className="border-t border-line first:border-0">
    <Disclosure className="min-w-0 border-0 rounded-none" summary={<span className="flex min-w-0 flex-wrap items-start gap-3"><span className="text-sm font-medium text-ink">{r.title}</span><Badge tone={r.passed ? 'good' : 'bad'}>{r.passed ? 'Passed' : 'Failed'}</Badge></span>}>
      <div className="space-y-3 pb-2">
        <p className="max-w-[72ch] text-[13px] leading-relaxed text-ink-2">{r.guarantee}</p>
        <div className="space-y-2 text-[13px] leading-relaxed text-ink-2">
          <p>{r.check_id === 'duplicate_apply' ? 'Expected: the data rules should reuse the existing receipt and prevent a second write.' : r.layer_expected === 'none' ? 'Expected: no stopping gate; this check exercises a permitted action or recovery evidence.' : `Expected: ${layerName(String(r.layer_expected))} should stop the unsafe request.`}</p>
          <p>{actual === null ? 'Recorded: the suite did not record a deciding gate.' : actual === 'none' ? 'Recorded: no stopping gate was reported.' : `Recorded: ${layerName(actual)} made the deciding response.`}{mismatch ? ' A different gate acted than expected; the recorded result is preserved.' : ''}</p>
          <p>The check took {formatDuration(r.duration_ms)}.</p>
          {evidence.length ? <p>{evidence.join(' ')}</p> : <p>{r.passed ? 'The suite recorded that this guarantee held.' : 'The recorded observations did not verify this guarantee.'} {Object.keys(r.evidence ?? {}).length ? 'The complete evidence is available in Technical mode.' : 'No extra evidence was recorded.'}</p>}
        </div>
        <Technical><dl className="flex flex-wrap gap-x-6 gap-y-3 text-xs">
          <div><dt className="mb-1 text-ink-3">Expected layer</dt><dd><LayerOrText value={String(r.layer_expected)} /></dd></div>
          <div><dt className="mb-1 text-ink-3">Actual layer</dt><dd><LayerOrText value={actual} /></dd></div>
          <div><dt className="mb-1 text-ink-3">Duration</dt><dd className="tabular text-ink-2">{formatDuration(r.duration_ms)}</dd></div>
        </dl></Technical>
        {r.error && <p className="text-[13px] text-block">The check reported an error. Open the raw record in Technical mode for its full message.</p>}
        <Technical><Disclosure summary="Raw record"><p className="mb-3 break-all font-mono text-xs text-ink-3">{r.check_id}{r.source_actual ? ' · ' + r.source_actual : ''}</p><pre className="max-h-72 max-w-full overflow-auto rounded-xl bg-sunken p-3 font-mono text-xs leading-relaxed text-ink-2">{JSON.stringify(r, null, 2)}</pre></Disclosure></Technical>
      </div>
    </Disclosure>
  </li>
}
export interface GuaranteeMatrixProps { results: VerificationResult[]; running: boolean }
export function GuaranteeMatrix({ results, running }: GuaranteeMatrixProps) {
  return <div className="space-y-2">
    {GROUPS.map(g => {
      const rows = results.filter(r => groupOf(r) === g.id)
      if (!rows.length) return null
      const passed = rows.filter(r => r.passed).length
      return <Disclosure key={g.id} summary={<span className="flex flex-wrap items-center gap-x-5 gap-y-2"><span className="font-medium text-ink">{g.title}</span><Badge tone={passed === rows.length ? 'good' : 'bad'}>{passed} of {rows.length} passed</Badge></span>}>
        <p className="mb-3 text-[13px] text-ink-2">{g.blurb}</p>
        <ul>{rows.map(r => <ResultRow key={r.check_id} result={r} />)}</ul>
      </Disclosure>
    })}
    {running && <p className="text-[13px] text-ink-3">Completed checks appear here as the suite publishes them.</p>}
  </div>
}
