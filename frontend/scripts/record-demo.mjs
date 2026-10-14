import { execFileSync } from 'node:child_process'
import { mkdir, readdir, rename, rm, symlink } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const outputDir = path.join(root, 'docs/video')
const recordingDir = path.join(outputDir, '.recording')
const videoPath = path.join(outputDir, 'veerIQ-demo.webm')
const browserPath = '/Users/ayushchougula/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
const verifier = path.join(root, 'scripts/veeriq-verify')
const evidencePath = path.join(root, 'docs/evidence/merged/import-live-sealed.json')
const holdPath = path.join(root, 'docs/evidence/merged/hold-rule-first-check.json')

await mkdir(outputDir, { recursive: true })
await rm(recordingDir, { recursive: true, force: true })
await mkdir(recordingDir, { recursive: true })
const ffmpegDir = path.join(recordingDir, 'ffmpeg-1013')
await mkdir(ffmpegDir, { recursive: true })
await symlink('/opt/homebrew/bin/ffmpeg', path.join(ffmpegDir, 'ffmpeg-mac'))
process.env.PLAYWRIGHT_BROWSERS_PATH = recordingDir
const { chromium } = await import('@playwright/test')

function verify(file) {
  try {
    return { code: 0, output: execFileSync(verifier, [file], { cwd: '/tmp', encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim() }
  } catch (error) {
    return { code: error.status ?? 1, output: (error.stderr || error.stdout || String(error)).trim() }
  }
}

const liveVerification = verify(evidencePath)
const validVerification = verify(path.join(root, 'verification/samples/valid-live-recovery.json'))
const tamperedVerification = verify(path.join(root, 'verification/samples/tampered-live-recovery.json'))
if (liveVerification.code !== 0 || validVerification.code !== 0 || tamperedVerification.code === 0) {
  throw new Error('Verifier output did not match the expected live, valid-sample, and tampered-sample results.')
}

const browser = await chromium.launch({ headless: true, executablePath: browserPath })
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 1,
  recordVideo: { dir: recordingDir, size: { width: 1600, height: 1000 } },
})
const page = await context.newPage()
page.setDefaultTimeout(30000)
page.on('pageerror', (error) => console.error('Browser page error:', error.message))

async function caption(text, ms = 1800) {
  await page.evaluate((label) => {
    let item = document.getElementById('recording-caption')
    if (!item) {
      item = document.createElement('div')
      item.id = 'recording-caption'
      Object.assign(item.style, {
        position: 'fixed', inset: 'auto 36px 26px', zIndex: '2147483647',
        padding: '15px 22px', borderRadius: '10px', background: 'rgba(20, 29, 38, .94)',
        color: '#fff', font: '500 20px/1.4 system-ui, sans-serif', boxShadow: '0 8px 32px #0004',
        textAlign: 'center', pointerEvents: 'none',
      })
      document.body.append(item)
    }
    item.textContent = label
  }, text)
  await page.waitForTimeout(ms)
}

await page.goto('http://127.0.0.1:5173/import', { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Warehouse stock locations' }).waitFor({ state: 'visible' })
await page.getByText('Viewing as', { exact: true }).waitFor({ state: 'visible' })
await caption('VeerIQ · sample import recovery · synthetic warehouse records', 2400)

await page.getByRole('button', { name: 'Warehouse stock locations' }).click()
await page.waitForFunction(() => (document.querySelector('#source-0')?.value?.length ?? 0) > 0)
await page.evaluate(() => window.scrollTo({ top: 560, behavior: 'instant' }))
await caption('Load current records, an approved snapshot, and separate authority data.', 2400)

const validateButton = page.getByRole('button', { name: 'Validate and preview' })
await validateButton.scrollIntoViewIfNeeded()
await caption('The import binds the snapshot digest and restricts eligible repair columns to quantity and location.', 2700)
await validateButton.click()
await page.getByRole('heading', { name: 'Validated comparison' }).waitFor({ state: 'visible' })
await page.getByRole('heading', { name: 'Validated comparison' }).scrollIntoViewIfNeeded()
await caption('Validated comparison · SKU-402 is damaged; held, revoked, and later-edited rows stay protected.', 2800)

const reviewButton = page.getByRole('button', { name: 'Review repair permission' })
await reviewButton.click()
await page.getByRole('heading', { name: 'Authorize this exact repair scope' }).waitFor({ state: 'visible' })
await page.getByRole('heading', { name: 'Authorize this exact repair scope' }).scrollIntoViewIfNeeded()
await caption('Review the grant for this tenant, record, and the two repairable fields.', 2400)

const startButton = page.getByRole('button', { name: 'Authorize and start scripted recovery' })
const runResponsePromise = page.waitForResponse((response) =>
  response.request().method() === 'POST' && response.url().endsWith('/api/runs'),
)
await startButton.click()
const runResponse = await runResponsePromise
if (!runResponse.ok()) throw new Error(`Starting the import recovery failed: ${runResponse.status()}`)
const startedRun = await runResponse.json()
await page.getByRole('heading', { name: 'Imported recovery result' }).waitFor({ state: 'visible', timeout: 60000 })
await page.waitForFunction(async (runId) => {
  const response = await fetch(`/api/runs/${runId}?fresh=${Date.now()}`, { cache: 'no-store' })
  if (!response.ok) return false
  const detail = await response.json()
  return ['succeeded', 'partially_succeeded', 'blocked', 'failed', 'cancelled'].includes(detail.run.status)
}, startedRun.run_id, { timeout: 120000, polling: 1000 })
await page.goto(`http://127.0.0.1:5173/runs/${startedRun.run_id}?recording=${Date.now()}`, { waitUntil: 'networkidle' })
let finalLabel = ''
for (let attempt = 0; attempt < 40; attempt += 1) {
  const visibleStatus = await page.locator('body').innerText()
  finalLabel = ['Partly repaired', 'Stopped', 'Failed', 'Cancelled', 'Repaired'].find((label) => visibleStatus.split('\n').includes(label)) ?? ''
  if (finalLabel) break
  await page.waitForTimeout(1000)
  await page.reload({ waitUntil: 'networkidle' })
}
if (!finalLabel) throw new Error(`Run ${startedRun.run_id} reached a final API state, but its final status did not appear in the VeerIQ UI.`)
await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
const finalUiText = await page.locator('body').innerText()
const liveLabel = finalUiText.includes('Live ArmorIQ') ? 'Live ArmorIQ' : finalUiText.includes('Simulated ArmorIQ') ? 'Simulated ArmorIQ' : 'ArmorIQ mode not shown'
const commitCount = finalUiText.match(/Recorded database commits\s+(\d+)/)?.[1]
await caption(`Run ${startedRun.run_id} · ${finalLabel} · ${liveLabel} · ${commitCount ?? 'result'} recorded commits.`, 3400)

const holdRecord = JSON.parse(await (await import('node:fs/promises')).readFile(holdPath, 'utf8'))
const holdDecision = holdRecord.apply_check?.[0]?.decisions?.find((item) => item.source === 'armoriq.backend.enforce')
const holdOutcome = holdDecision?.outcome?.toUpperCase() ?? 'UNAVAILABLE'

const esc = (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
const evidenceSlate = `<!doctype html><html><head><meta charset="utf-8"><title>Recorded verification evidence</title><style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f3f5f7;font:20px/1.5 system-ui,sans-serif}.wrap{max-width:1400px;margin:auto;padding:58px 70px}.eyebrow{font-size:15px;letter-spacing:.16em;text-transform:uppercase;color:#91a9ba}h1{font-size:43px;line-height:1.15;margin:12px 0 28px}h2{font-size:22px;margin:28px 0 8px;color:#c8d8e2}.badge{display:inline-block;border:1px solid #47b881;color:#7ed9a8;padding:4px 12px;border-radius:99px;font-size:15px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#18242e;border:1px solid #344450;border-radius:12px;padding:18px 22px;font:15px/1.5 ui-monospace,monospace;color:#e4edf2}.note{margin-top:26px;padding:18px 22px;border-left:4px solid #e7a348;background:#27251f;color:#f5dcae}.sub{font-size:16px;color:#acbac3}
</style></head><body><main class="wrap"><div class="eyebrow">Recorded local CLI output · offline evidence verifier</div><h1>Evidence checks run independently of the app</h1><p class="sub">The displayed output below was produced by this recording script from the repository verifier. Each result names its input.</p>
<h2>Previously recorded live import evidence · ${esc(evidencePath.split('/').slice(-1)[0])}</h2><span class="badge">PASS · ${esc(liveVerification.output.match(/VERIFIED run ([^\n]+)/)?.[1] ?? 'verified')}</span><pre>${esc(liveVerification.output)}</pre>
<h2>Valid public sample</h2><span class="badge">PASS</span><pre>${esc(validVerification.output)}</pre>
<h2>Deliberately tampered public sample</h2><span class="badge" style="border-color:#d87676;color:#ffaaaa">REJECTED · expected</span><pre>Exit status ${tamperedVerification.code}\n${esc(tamperedVerification.output)}</pre>
<div class="note">The repository’s bundled public key confirms consistency with that key. This check does not establish independent signer identity or ArmorIQ attestation.</div></main></body></html>`

await page.setContent(evidenceSlate, { waitUntil: 'load' })
await page.waitForTimeout(3500)

const holdSlate = `<!doctype html><html><head><meta charset="utf-8"><title>HOLD status</title><style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#f3f5f7;font:22px/1.5 system-ui,sans-serif}.wrap{max-width:1300px;margin:auto;padding:100px 78px}.eyebrow{font-size:16px;letter-spacing:.16em;text-transform:uppercase;color:#91a9ba}h1{font-size:52px;line-height:1.15;margin:18px 0 32px}.status{display:inline-block;padding:8px 18px;border:2px solid #e7a348;border-radius:8px;color:#ffd28b;font-weight:700;letter-spacing:.06em}.card{margin-top:35px;padding:26px 30px;border:1px solid #46545f;border-radius:14px;background:#18242e}.muted{color:#b6c4cd;font-size:18px}.reason{margin-top:24px;color:#ffe0b2}.source{margin-top:48px;color:#8ea0ad;font-size:15px}
</style></head><body><main class="wrap"><div class="eyebrow">ArmorIQ sponsor approval evidence status</div><h1>Requested HOLD is not demonstrated</h1><div class="status">HOLD · NOT VERIFIED</div><section class="card"><p>In the isolated USD 12,400 rehearsal, the recorded sponsor decision was <strong>${esc(holdOutcome)}</strong>.</p><p class="muted">The available response allowed the apply action. No live amount-specific HOLD policy or approval round trip is recorded for this dashboard session.</p><p class="reason">This recording does not claim a HOLD, pending delegation, or sponsor approval. The import flow above shows its actual ArmorIQ mode in the result card.</p></section><p class="source">Source: docs/evidence/merged/hold-rule-first-check.json · ${esc(holdRecord.observation)}</p></main></body></html>`
await page.setContent(holdSlate, { waitUntil: 'load' })
await page.waitForTimeout(4200)

await context.close()
await browser.close()
const recordings = await readdir(recordingDir)
const videoFile = recordings.find((name) => name.endsWith('.webm'))
if (!videoFile) throw new Error('Playwright did not produce a video file.')
await rm(videoPath, { force: true })
await rename(path.join(recordingDir, videoFile), videoPath)
await rm(recordingDir, { recursive: true, force: true })
console.log(`Recorded ${videoPath}`)
