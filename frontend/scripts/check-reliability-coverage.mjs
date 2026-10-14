import {chromium} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import {writeFile} from 'node:fs/promises'
const file=process.argv[2]
if(!/^reliability-\d{8}T\d{6}Z\.json$/.test(file??''))throw Error('Pass a UTC reliability artifact filename')
const browser=await chromium.launch(process.env.VEERIQ_CHROMIUM_PATH?{executablePath:process.env.VEERIQ_CHROMIUM_PATH}:{})
const context=await browser.newContext({viewport:{width:1440,height:1000}})
const page=await context.newPage()
await page.goto('http://127.0.0.1:5173/proof')
await page.getByLabel(/Measured batch/).selectOption(file)
await page.getByText('Collection in progress; results are provisional',{exact:false}).waitFor()
const response=await page.request.get('http://127.0.0.1:5173/api/evidence/reliability?file='+encodeURIComponent(file))
if(!response.ok())throw Error('Cohort evidence API unavailable')
const data=await response.json()
if(data.requested_trials!==40||data.finished_at||data.trials.length>=40)throw Error('Partial cohort is incorrectly marked complete')
const pending=Object.entries(data.summary).filter(([,g])=>g.trials===0)
for(const [key]of pending){const row=page.getByRole('row').filter({hasText:key.split('|')[0]});if(!(await row.innerText()).includes('Not observed'))throw Error('Unstarted group has no absence-of-evidence label')}
const layouts=[]
for(const width of [1440,390]){await page.setViewportSize({width,height:1000});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Proof layout overflow');const audit=await new AxeBuilder({page}).analyze();const issues=audit.violations.filter(v=>['serious','critical'].includes(v.impact));if(issues.length)throw Error('Proof accessibility failed: '+JSON.stringify(issues.map(x=>({id:x.id,targets:x.nodes.map(n=>n.target)}))));layouts.push({width,serious_critical:0,overflow:false})}
await writeFile('../docs/evidence/partial-cohort-ui.json',JSON.stringify({observed_at:new Date().toISOString(),source:'actual local API and browser observation',file,requested_trials:data.requested_trials,recorded_trials:data.trials.length,provisional:true,unstarted_groups:pending.map(([k])=>k),unstarted_group_effects_label:'Not observed',layouts},null,2)+'\n')
await context.close();await browser.close();console.log('Partial 40-trial cohort shown provisionally; unstarted groups not counted as zero-effects proof')
