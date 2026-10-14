import { describe, expect, it } from 'vitest'
import { TERMINAL_RUN_STATUSES, type RunStatus } from '@/api/types'
import {
  RUN_STATUS,
  invariantLabel,
  normaliseWarnings,
  plannerBadgeText,
  plannerLabel,
  providerLabel,
  resourceLabel,
  splitPlanner,
  tenantName,
  toolLabel,
  toolSummary,
  fieldLabel,
} from './labels'

describe('tool and field labels', () => {
  it('uses the plain label for a known tool and its summary', () => {
    expect(toolLabel('apply_repair_manifest')).toBe('Apply repair')
    expect(toolSummary('apply_repair_manifest')).toBe('Commit the prepared repair in one transaction')
  })

  it('falls back to a title-cased name for an unknown tool, with no summary', () => {
    expect(toolLabel('vendor_export_csv')).toBe('Vendor export csv')
    expect(toolSummary('vendor_export_csv')).toBe('')
  })

  it('maps a known field to its label and title-cases an unknown one', () => {
    expect(fieldLabel('total_cents')).toBe('Order total')
    expect(fieldLabel('loyalty_tier')).toBe('Loyalty tier')
  })
})

describe('resourceLabel and tenantName', () => {
  it('uses the singular only for exactly one item, including zero as plural', () => {
    expect(resourceLabel('order')).toBe('orders')
    expect(resourceLabel('order', 1)).toBe('order')
    expect(resourceLabel('order', 0)).toBe('orders')
  })

  it('title-cases an unknown resource kind', () => {
    expect(resourceLabel('invoice', 1)).toBe('Invoice')
  })

  it('names a known tenant and title-cases an unknown tenant id', () => {
    expect(tenantName('atlas')).toBe('Atlas Outfitters')
    expect(tenantName('northwind-retail')).toBe('Northwind retail')
  })
})

describe('invariant labels', () => {
  it('uses the plain sentence for a known invariant id', () => {
    expect(invariantLabel('tool_not_granted')).toBe('Tool not in the grant')
  })

  it('title-cases an unknown invariant id and returns empty for a missing one', () => {
    expect(invariantLabel('new_check')).toBe('New check')
    expect(invariantLabel(null)).toBe('')
  })
})

describe('run status', () => {
  it('marks a run live exactly when it has not reached a terminal status', () => {
    const terminal = new Set<RunStatus>(TERMINAL_RUN_STATUSES)
    for (const [status, meta] of Object.entries(RUN_STATUS)) {
      expect(meta.live, status).toBe(!terminal.has(status as RunStatus))
    }
  })
})

describe('planner labels', () => {
  it('splits "<provider>:<model>" where the model may itself contain a slash or colon', () => {
    expect(splitPlanner('groq:openai/gpt-oss-120b')).toEqual({ provider: 'groq', model: 'openai/gpt-oss-120b' })
    expect(splitPlanner('a:b:c')).toEqual({ provider: 'a', model: 'b:c' })
  })

  it('returns null when there is no provider to split off', () => {
    expect(splitPlanner(':model')).toBeNull()
    expect(splitPlanner('noseparator')).toBeNull()
  })

  it('names a provider, and title-cases one it does not know', () => {
    expect(providerLabel('GROQ')).toBe('Groq')
    expect(providerLabel('mistral')).toBe('Mistral')
    expect(providerLabel(null)).toBe('')
  })

  it('builds a label from the provider and the model without its vendor prefix', () => {
    expect(plannerLabel('groq:openai/gpt-oss-120b', 'llm')).toBe('Groq gpt-oss-120b')
  })

  it('prefers the server label when one is given', () => {
    expect(plannerLabel('groq:openai/gpt-oss-120b', 'llm', 'Groq, GPT OSS 120B')).toBe('Groq, GPT OSS 120B')
  })

  it('names scripted and harness runs for what they are, with no model name', () => {
    expect(plannerLabel('scripted', 'scripted')).toBe('Scripted agent (no LLM)')
    expect(plannerLabel('harness', 'harness')).toBe('Boundary harness')
  })

  it('never badges a scripted run as a live LLM', () => {
    expect(plannerBadgeText('scripted', 'scripted')).toBe('Scripted re-enactment')
    expect(plannerBadgeText('scripted', 'scripted')).not.toMatch(/live/i)
  })

  it('badges an LLM run as live and names its model', () => {
    expect(plannerBadgeText('groq:openai/gpt-oss-120b', 'llm')).toBe('Live LLM: Groq gpt-oss-120b')
  })
})

describe('normaliseWarnings', () => {
  it('returns an empty list when there are no warnings', () => {
    expect(normaliseWarnings(undefined)).toEqual([])
  })

  it('marks a string warning about unavailable or simulated enforcement as a warning', () => {
    expect(normaliseWarnings(['ArmorIQ is unreachable from this host'])).toEqual([
      { level: 'warn', code: 'ArmorIQ is unreachable from this host', message: 'ArmorIQ is unreachable from this host' },
    ])
    expect(normaliseWarnings(['Enforcement is simulated'])[0]?.level).toBe('warn')
  })

  it('marks any other string warning as information', () => {
    expect(normaliseWarnings(['Fixture data is fresh'])[0]?.level).toBe('info')
  })

  it('truncates the code of a long string warning but keeps the full message', () => {
    const message = 'x'.repeat(60)
    const [warning] = normaliseWarnings([message])
    expect(warning?.code).toHaveLength(40)
    expect(warning?.message).toBe(message)
  })

  it('passes structured warnings through unchanged', () => {
    const structured = { level: 'error' as const, code: 'db_down', message: 'Database unreachable' }
    expect(normaliseWarnings([structured])).toEqual([structured])
  })
})
