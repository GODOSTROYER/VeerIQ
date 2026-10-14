#!/usr/bin/env node
/**
 * Full-page screenshots of the running dev UI, for visual QA.
 *
 *   node scripts/capture.mjs --out ../.shots/before --routes /,/approvals --as maya --width 1440
 *   node scripts/capture.mjs --out ../.shots/m --routes / --width 390 --height 844
 *
 * Needs the Vite dev server (default http://127.0.0.1:5173) and the backend running.
 * Uses the project's `playwright` if installed, otherwise the global @playwright/cli copy.
 */
import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createRequire } from 'node:module'

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, cur, i, arr) => {
    if (cur.startsWith('--')) acc.push([cur.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : 'true'])
    return acc
  }, []),
)
const base = args.base ?? 'http://127.0.0.1:5173'
const out = resolve(args.out ?? '.shots')
const routes = (args.routes ?? '/').split(',')
const width = Number(args.width ?? 1440)
const height = Number(args.height ?? 900)
const as = args.as ?? 'maya'
const settle = Number(args.settle ?? 1800)
const fullPage = args.viewport !== 'true'

async function loadPlaywright() {
  try {
    return await import('playwright')
  } catch {
    const require = createRequire(import.meta.url)
    const globalRoot = join(process.env.APPDATA ?? '', 'npm', 'node_modules', '@playwright', 'cli', 'node_modules', 'playwright')
    return require(globalRoot)
  }
}

const { chromium } = await loadPlaywright()
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'dark' })
const page = await context.newPage()
await page.goto(base, { waitUntil: 'domcontentloaded' })
await page.evaluate(async (id) => {
  await fetch('/api/session', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ identity_id: id }), credentials: 'include' })
}, as)

for (const route of routes) {
  await page.goto(base + route, { waitUntil: 'networkidle' }).catch(() => undefined)
  await page.waitForTimeout(settle)
  const name = (route === '/' ? 'home' : route.replace(/^\//, '').replace(/[/?=&]+/g, '_')) + `-${width}.png`
  await page.screenshot({ path: join(out, name), fullPage })
  console.log(join(out, name))
}
await browser.close()
