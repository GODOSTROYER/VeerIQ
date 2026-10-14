import {chromium} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import {writeFile} from 'node:fs/promises'
const browser=await chromium.launch(process.env.VEERIQ_CHROMIUM_PATH?{executablePath:process.env.VEERIQ_CHROMIUM_PATH}:{})
const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const page=await context.newPage()
let attempts=0
await page.route('**/api/grants/*/authorize',async route=>{attempts++;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'UI acceptance test: authorization intercepted; no run started.'})})})
await page.goto('http://127.0.0.1:5173/');await page.getByRole('button',{name:'Review grant',exact:true}).first().click()
const currentGrant=page.getByRole('button',{name:'Review current-data grant',exact:true});await currentGrant.waitFor({timeout:10000});await currentGrant.click()
const hold=page.getByRole('button',{name:/Hold to authorize & start/})
await hold.waitFor();await hold.focus()
await page.keyboard.down('Enter');await page.waitForTimeout(200);await page.keyboard.up('Enter');await page.waitForTimeout(150)
if(attempts!==0)throw Error('Short hold authorized')
await hold.focus();await page.keyboard.down('Enter');await page.waitForTimeout(1250);await page.keyboard.up('Enter')
await page.waitForTimeout(350)
if(attempts!==1)throw Error('Keyboard long hold did not fire exactly once')
const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze()
const serious=audit.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,impact:v.impact}))
await writeFile('../docs/evidence/hold-keyboard-audit.json',JSON.stringify({observed_at:new Date().toISOString(),source:'real rendered modal; authorization request intercepted for UI test, no authorization or run performed',short_hold_cancelled:true,long_keyboard_hold_requests:attempts,reduced_motion:true,serious_critical:serious},null,2))
await browser.close();if(serious.length)throw Error('Modal serious accessibility issue')
console.log('Keyboard hold cancellation/single activation and modal axe checks passed')
