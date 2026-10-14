export function WhyRecovery() {
  return <section className="border-y border-line py-6" aria-labelledby="why-recovery-title">
    <h2 id="why-recovery-title" className="text-xl font-semibold text-ink">A backup remembers old permissions, too.</h2>
    <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">In this synthetic incident, replacing today’s state with the whole snapshot would reverse four legitimate decisions. Repairing selected damaged values avoids that collateral change.</p>
    <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="Restore comparison"><table className="w-full min-w-[520px] text-left text-sm"><caption className="sr-only">Hypothetical whole-snapshot replacement compared with selective recovery on the demo incident</caption><thead className="border-b border-line"><tr><th className="py-3 pr-4">Today’s decision</th><th className="py-3 pr-4">Whole-snapshot replacement</th><th className="py-3">VeerIQ repair requirement</th></tr></thead><tbody className="divide-y divide-line text-ink-2">{[
      ['Service account revoked','Access becomes active again','Keep access revoked'],
      ['Customer erased','Deleted customer returns','Keep customer deleted'],
      ['Order deleted','Deleted order returns','Keep order deleted'],
      ['Order shipped after snapshot','Shipment status rolls back','Keep later shipment update'],
    ].map(row=><tr key={row[0]}>{row.map((cell,i)=><td key={i} className="py-3 pr-4">{cell}</td>)}</tr>)}</tbody></table></div>
    <p className="mt-4 max-w-3xl text-xs leading-relaxed text-ink-3">This is a modeled comparison, not an executed unsafe restore or an industry loss statistic. The underlying obligations are real: <a href="https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng/" target="_blank" rel="noreferrer" className="underline underline-offset-4">GDPR Article 17 addresses erasure</a>, and <a href="https://csrc.nist.gov/glossary/term/least_privilege" target="_blank" rel="noreferrer" className="underline underline-offset-4">NIST defines least privilege</a>. This prototype does not certify compliance.</p>
  </section>
}
