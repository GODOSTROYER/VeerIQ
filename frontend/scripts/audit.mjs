import { chromium } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
const base=process.env.VEERIQ_AUDIT_URL??'http://127.0.0.1:5173'
const browser=await chromium.launch(process.env.VEERIQ_CHROMIUM_PATH?{executablePath:process.env.VEERIQ_CHROMIUM_PATH}:{})
const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'})
const page=await context.newPage()
const results=[]
await mkdir('../docs/img',{recursive:true})
const runEvidence=JSON.parse(await readFile('../docs/evidence/historical-check-observation.json','utf8'))
for(const path of ['/','/import','/how','/walkthrough','/proof','/approvals',`/runs/${runEvidence.run_id}`,`/runs/${runEvidence.legacy_import_run}`]){
 await page.goto(base+path);await page.waitForTimeout(1300)
 if(path.startsWith('/runs/')){const response=await page.request.get(base+'/api'+path);if(!response.ok())throw Error(`Required recorded run is unavailable (${response.status()}): ${path}`)}
 const audit=await new AxeBuilder({page}).analyze()
 const name=path==='/'?'landing':path.slice(1).replaceAll('/','-')
 const issues=audit.violations.filter(v=>['serious','critical'].includes(v.impact))
 const layouts=[]
 for(const width of [1280,1440,1920,390]){
  await page.setViewportSize({width,height:width===390?844:1000})
  await page.screenshot({path:`../docs/img/${name}-${width}.png`,fullPage:true})
  layouts.push({width,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)})
 }
 results.push({path,serious_critical:issues.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.map(n=>n.target)})),all_violations:audit.violations.map(v=>({id:v.id,impact:v.impact})),layouts})
 console.log(path,'serious/critical:',issues.length)
 await page.setViewportSize({width:1440,height:1000})
}
await page.goto(base+'/how');await page.waitForSelector('[data-flow-step="-1"]')
await page.getByRole('button',{name:'Start request',exact:true}).click()
await page.waitForTimeout(1800)
if(await page.locator('[data-flow-step]').getAttribute('data-flow-step')!=='0')throw Error('Explanation advanced automatically')
await page.getByRole('button',{name:'Next check',exact:true}).press('Enter')
if(await page.locator('[data-flow-step]').getAttribute('data-flow-step')!=='1')throw Error('Keyboard next step failed')
results.push({manual_flow:{automatic_advance:false,keyboard_next:true,reduced_motion:await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches)}})
await writeFile('../docs/evidence/ui-audit.json',JSON.stringify({observed_at:new Date().toISOString(),base,results},null,2))
await browser.close()
if(results.some(r=>r.serious_critical?.length||r.layouts?.some(l=>l.overflow)))process.exitCode=1
