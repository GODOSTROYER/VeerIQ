import { useEffect, useRef } from 'react'
import type { RunMetrics } from '@/api/types'
import type { ProposalItem } from './model'
import { toolLabel } from '@/lib/labels'

/** A view of one actual proposal; it never authorizes or executes an action. */
export function AuthorityBoundary({ proposal, metrics, replaying }: { proposal?: ProposalItem; metrics?: RunMetrics; replaying: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const outcome = proposal?.status === 'executed' ? 'allow' : proposal?.status === 'blocked' ? 'deny' : proposal?.status === 'held' ? 'hold' : 'pending'
  useEffect(() => {
    const node=canvas.current
    if (!node) return
    const ctx=node.getContext('2d')
    if (!ctx) return
    let frame=0, visible=true, disposed=false
    const preference=matchMedia('(prefers-reduced-motion: reduce)')
    function draw(time: number) {
      if (!ctx || !node || disposed) return
      const width=node.clientWidth, height=115, ratio=Math.min(devicePixelRatio,2)
      if(node.width!==width*ratio||node.height!==height*ratio){node.width=width*ratio;node.height=height*ratio}
      ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height)
      const split=width*.57, y=62, style=getComputedStyle(node)
      ctx.strokeStyle=style.getPropertyValue('--border-strong');ctx.lineWidth=1
      ctx.beginPath();ctx.moveTo(12,y);ctx.lineTo(width-12,y);ctx.stroke()
      ctx.strokeStyle=style.getPropertyValue('--layer-armoriq');ctx.beginPath();ctx.moveTo(split,14);ctx.lineTo(split,100);ctx.stroke()
      const end=outcome==='allow'?width-16:split-12
      const progress=preference.matches?1:Math.min(1,(time%3600)/2200)
      ctx.fillStyle=style.getPropertyValue(outcome==='deny'?'--outcome-block':outcome==='hold'?'--outcome-hold':'--layer-armoriq')
      const x=16+(end-16)*progress;ctx.fillRect(x-4,y-4,8,8)
      if(progress===1&&outcome!=='allow'){ctx.beginPath();ctx.moveTo(split-13,y-10);ctx.lineTo(split-13,y+10);ctx.stroke()}
      if(visible&&!preference.matches)frame=requestAnimationFrame(draw)
    }
    const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;cancelAnimationFrame(frame);if(visible)draw(performance.now())})
    observer.observe(node)
    const update=()=>{cancelAnimationFrame(frame);draw(performance.now())}
    const resize=new ResizeObserver(update);resize.observe(node);preference.addEventListener('change',update)
    draw(performance.now())
    return()=>{disposed=true;cancelAnimationFrame(frame);observer.disconnect();resize.disconnect();preference.removeEventListener('change',update)}
  },[outcome])
  const measured=metrics&&!replaying
  return <section className="authority-boundary" aria-label="Execution boundary and observed effects">
    <div className="boundary-mechanism">
      <div className="boundary-caption"><span>Agent proposal</span><span className="boundary-label">Authority boundary</span><span>Execution</span></div>
      <canvas ref={canvas} aria-hidden />
      <p className="text-xs text-ink-2">{proposal ? `${toolLabel(proposal.tool)} · ${outcome==='allow'?'executed':outcome==='deny'?'stopped before handler':outcome==='hold'?'waiting for approval':'awaiting a decision'}` : 'Waiting for a recorded proposal. No action is assumed allowed.'}</p>
    </div>
    <div className="boundary-effect">
      <div><span>Prohibited handler entries</span><strong>{measured?metrics.prohibited_handler_entries:'Not reported'}</strong></div>
      <div><span>Forbidden effects observed</span><strong>{measured?metrics.forbidden_effects_observed:'Not reported'}</strong></div>
      <div><span>Recorded database commits</span><strong>{measured?metrics.commits:'Not reported'}</strong></div>
      <p>{replaying?'Current final counters are hidden during replay.':'Measured from the recovery runtime and durable database state. The evidence export binds the event sequence and observed outcome.'}</p>
    </div>
  </section>
}
