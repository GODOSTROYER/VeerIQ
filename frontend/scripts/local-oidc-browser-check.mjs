import { readFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const root = new URL('../../', import.meta.url)
const privateDir = new URL('.local-oidc/', root)
const appOrigin = 'https://localhost:8443'
const lines = (await readFile(new URL('credentials.txt', privateDir), 'utf8')).split(/\r?\n/)
const accounts = lines.flatMap((line) => {
  if (line.startsWith('Admin:') || !line.includes(': ') || !line.includes(' / ')) return []
  const [label, details] = line.split(': ', 2)
  const [tenant, role] = label.split(' ', 2)
  const [username, password] = details.split(' / ', 2)
  return [{ tenant, role, username, password }]
})

if (accounts.length !== 3) throw new Error('Private local fixture account file is incomplete.')

const executablePath = process.env.VEERIQ_CHROMIUM_PATH
  ?? '/Users/ayushchougula/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
const browser = await chromium.launch({ executablePath, headless: true })
try {
  for (const account of accounts) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true })
    const page = await context.newPage()
    await page.goto(appOrigin, { waitUntil: 'domcontentloaded' })
    await page.getByRole('link', { name: 'Sign in with your organization' }).click()
    await page.locator('input[name="username"]').fill(account.username)
    await page.locator('input[name="password"]').fill(account.password)
    await page.getByRole('button', { name: 'Sign In' }).click()
    await page.waitForURL((url) => url.origin === appOrigin, { timeout: 30000 })
    await page.waitForFunction(async () => {
      const response = await fetch('/api/session')
      return response.status === 200
    }, undefined, { timeout: 20000 })
    const identity = await page.evaluate(async () => (await fetch('/api/session')).json())
    if (identity.role !== account.role || identity.tenant_id !== account.tenant) {
      throw new Error(`Browser identity mapping failed for fixture role ${account.role}.`)
    }
    const [sessionCookie] = (await context.cookies(appOrigin)).filter((cookie) => cookie.name === 'rs_session')
    if (!sessionCookie?.httpOnly || !sessionCookie.secure || !sessionCookie.value) {
      throw new Error(`Browser did not receive the secure opaque session for fixture role ${account.role}.`)
    }
    console.log(`PASS: isolated browser login mapped ${account.role} in ${account.tenant}; secure HttpOnly session issued.`)
    await context.close()
  }
} finally {
  await browser.close()
}
