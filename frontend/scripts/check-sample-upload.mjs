import {chromium} from '@playwright/test'
import {writeFile} from 'node:fs/promises'
import {execFileSync} from 'node:child_process'
const browser=await chromium.launch(process.env.VEERIQ_CHROMIUM_PATH?{executablePath:process.env.VEERIQ_CHROMIUM_PATH}:{})
const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}})
const page=await context.newPage()
await page.goto('http://127.0.0.1:5173/import')
await page.getByRole('button',{name:'Warehouse stock locations',exact:true}).click()
await page.waitForFunction(()=>document.querySelector('#source-0')?.value.length>0)
const started=Date.now()
const downloadPromise=page.waitForEvent('download')
await page.getByRole('link',{name:'Download Warehouse stock locations pack',exact:true}).click()
const download=await downloadPromise
const zip=await download.path()
const entryNames=execFileSync('unzip',['-Z1',zip],{encoding:'utf8'}).trim().split('\n')
const metadata=JSON.parse(execFileSync('unzip',['-p',zip,'pack.json'],{encoding:'utf8'}))
for(const [label,file] of [['Current records',metadata.current_file],['Approved snapshot',metadata.snapshot_file],['Authority records',metadata.authority_file]]){
 if(!entryNames.includes(file))throw Error('Sample archive is missing '+file)
 const buffer=execFileSync('unzip',['-p',zip,file])
 await page.getByLabel('Upload '+label,{exact:true}).setInputFiles({name:file,mimeType:file.endsWith('.csv')?'text/csv':'application/json',buffer})
}
await page.getByRole('button',{name:'Validate and preview',exact:true}).click()
await page.getByRole('heading',{name:'Validated comparison',exact:true}).waitFor()
await page.getByRole('button',{name:'Review repair permission',exact:true}).click()
await page.getByRole('heading',{name:'Authorize this exact repair scope',exact:true}).waitFor()
const grantText=await page.getByRole('heading',{name:'Authorize this exact repair scope',exact:true}).locator('..').innerText()
if(!grantText.includes('1 record'))throw Error('Imported grant is not labelled with record units')
const pending=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/runs'))
await page.getByRole('button',{name:'Authorize and start scripted recovery',exact:true}).click()
const response=await pending;if(!response.ok())throw Error('Run start failed')
const run=await response.json()
let detail
const deadline=Date.now()+120000
while(Date.now()<deadline){
 detail=await page.evaluate(async id=>await(await fetch('/api/runs/'+id)).json(),run.run_id)
 if(['succeeded','partially_succeeded','blocked','failed','cancelled'].includes(detail.run.status))break
 await page.waitForTimeout(1000)
}
if(detail.run.status!=='succeeded'||detail.metrics.commits!==1||detail.metrics.forbidden_effects_observed!==0)throw Error('Expected safe one-commit repair not observed: '+JSON.stringify({id:run.run_id,status:detail.run.status,metrics:detail.metrics}))
const elapsed=(Date.now()-started)/1000
if(elapsed>=180)throw Error('Automated import flow exceeded three minutes')
await writeFile('../docs/evidence/sample-upload-flow.json',JSON.stringify({observed_at:new Date().toISOString(),source:'automated real-browser sample download and three-file upload; not human timing',elapsed_seconds:elapsed,archive:download.suggestedFilename(),files:[metadata.current_file,metadata.snapshot_file,metadata.authority_file],mapping:'bundled metadata loaded through sample UI before uploading downloaded files',run_id:run.run_id,status:detail.run.status,planner:'scripted',enforcement:detail.run.enforcement_mode,commits:detail.metrics.commits,forbidden_effects:detail.metrics.forbidden_effects_observed,receipt_changes:detail.receipts.flatMap(r=>r.changes)},null,2))
await context.close();await browser.close();console.log('Downloaded pack and uploaded three files: safe repair in '+elapsed.toFixed(1)+' seconds')
