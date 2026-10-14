import {chromium} from '@playwright/test'
import {readFile,writeFile} from 'node:fs/promises'
const evidence=JSON.parse(await readFile('../docs/evidence/historical-check-observation.json','utf8'))
const browser=await chromium.launch(process.env.VEERIQ_CHROMIUM_PATH?{executablePath:process.env.VEERIQ_CHROMIUM_PATH}:{})
const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'})
const page=await context.newPage()
const observations=[]
for(const [kind,id] of [['new',evidence.run_id],['legacy',evidence.legacy_import_run]]){
 await page.goto(`http://127.0.0.1:5173/runs/${id}`)
 await page.getByRole('region',{name:'Recorded recovery results'}).waitFor()
 await page.waitForTimeout(1500)
 const scoreboard=await page.getByRole('region',{name:'Recorded recovery results'}).innerText()
 const body=await page.locator('body').innerText()
 if(!body.includes('Imported records')||!body.includes('SKU-402')||!body.includes('A-03-C'))throw Error('Imported receipt values missing')
 if(kind==='new'&&!scoreboard.includes(`All ${evidence.recorded_check_count} recorded checks preserved at run completion.`))throw Error('New run lacks recorded protected-check confirmation')
 if(kind==='legacy'&&!scoreboard.includes('Detailed historical protected checks were not recorded'))throw Error('Legacy run is incorrectly certified from current state')
 observations.push({kind,run_id:id,recorded_results:scoreboard,receipt_values_visible:true})
}
await writeFile('../docs/evidence/run-ui-verification.json',JSON.stringify({observed_at:new Date().toISOString(),source:'real local rendered UI; no mutations',observations},null,2))
await browser.close();console.log('New recorded checks and legacy missing-check labels verified; imported receipt values visible')
