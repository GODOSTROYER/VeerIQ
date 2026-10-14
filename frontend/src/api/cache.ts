/** Shared response cache so remounted views render instantly while revalidating. */
export const queryCache = new Map<string, unknown>()

/** Drop every cached response (called on identity change and demo reset). */
export function clearQueryCache(): void {
  queryCache.clear()
}
