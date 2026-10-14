/** Mix a CSS colour (usually a token reference) with transparency. */
export function tint(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`
}
