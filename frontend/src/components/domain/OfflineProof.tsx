import { useEffect, useState } from 'react'
type RecordedCheck = {observed_at:string;results:{file:string;exit_code:number;output:string}[]}
export function OfflineProof() {
  const [checks,setChecks]=useState<RecordedCheck|null>(null)
  useEffect(()=>{let active=true;fetch('/verification/verification-results.json').then(r=>r.ok?r.json():null).then(v=>{if(active)setChecks(v)}).catch(()=>{});return()=>{active=false}},[])
  return <section className="border border-line bg-raised p-5" aria-labelledby="offline-proof-title">
    <h3 id="offline-proof-title" className="text-lg font-semibold text-ink">Verify it without trusting the interface.</h3>
    <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">Download the export, published public key, and standalone verifier. It checks the signature, event chain, payload hash, and receipt digests offline. The deliberately altered copy must fail.</p>
    <div className="mt-4 flex flex-wrap gap-4 text-sm">
      <a className="underline underline-offset-4" href="/verification/valid-live-recovery.json" download>Valid export</a>
      <a className="underline underline-offset-4" href="/verification/audit-linked-scripted-live-sealed.json" download>Live ArmorIQ audit-linked export</a>
      <a className="underline underline-offset-4" href="/verification/tampered-live-recovery.json" download>Altered export</a>
      <a className="underline underline-offset-4" href="/verification/operator-public-key.pem" download>Recorded export public key</a>
      <a className="underline underline-offset-4" href="/verification/veeriq_verify.py" download>Verifier</a>
    </div>
    <pre className="mt-4 overflow-x-auto bg-sunken p-3 text-xs" tabIndex={0} role="region" aria-label="Offline verification command"><code>python3 veeriq_verify.py valid-live-recovery.json --trusted-key operator-public-key.pem</code></pre>
    <p className="mt-2 text-xs text-ink-3">The audit-linked export records a scripted repair with live ArmorIQ, its plan hash and five service-returned audit IDs; offline integrity is not sponsor attestation. Requires Python and cryptography. These samples use the recorded demo signer; a fresh deployment can have a different signing key.</p>
    <p className="mt-3 text-sm"><a className="underline underline-offset-4" href="/api/evidence/signing-public-key" download="workspace-public-key.pem">Download this workspace’s public key</a></p>
    <p className="mt-2 text-xs text-ink-3">For a newly downloaded run export, use this workspace key with --trusted-key workspace-public-key.pem. Obtain its fingerprint independently when signer identity matters; an API-delivered key is not independent attestation.</p>
    <details className="mt-4 border-t border-line pt-3">
      <summary className="min-h-11 cursor-pointer text-sm font-medium">Show the recorded valid and tampered checks</summary>
      <p className="mt-2 text-xs text-ink-3">Recorded local CLI output, not a new verification of your download. Run the command above to reproduce it.</p>
      {checks?checks.results.map(check=><div key={check.file} className="mt-4"><p className="text-sm font-medium">{check.file} · {check.exit_code===0?'Passed':'Rejected'} (exit {check.exit_code})</p><pre className="mt-2 overflow-auto bg-sunken p-3 text-xs" tabIndex={0} role="region" aria-label="Recorded verification output">{check.output}</pre></div>):<p className="mt-3 text-sm text-ink-3">Recorded results could not load. The downloadable samples and verifier remain available.</p>}
    </details>
  </section>
}
