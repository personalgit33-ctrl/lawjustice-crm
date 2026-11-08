'use client';
import { useState } from 'react';
import { download, get, post } from '@/lib/api';
import { Icon } from '@/components/Icon';
import { ChTag, Empty, Kpi, Modal, Seg, View, useLoad } from '@/components/ui';
import { toast, toastErr } from '@/components/toast';
import { money, num } from '@/lib/format';
import { t } from '@/i18n';
import type { FunnelReport } from '@/lib/types';

type P = 'week' | 'month' | 'quarter';
export default function ReportsPage() {
  const [p, setP] = useState<P>('month'); const [spend, setSpend] = useState(false);
  const s = useLoad(() => get<FunnelReport>(`reports/funnel/?period=${p}`), [p]);
  const exp = async () => { try { await download(`reports/funnel/export/?period=${p}`, 'funnel.xlsx'); toast('Отчёт выгружен в Excel'); } catch (e) { toastErr(e); } };
  return <>
    <div className="bhead"><Seg value={p} onChange={setP} options={[['week', 'Неделя'], ['month', 'Месяц'], ['quarter', 'Квартал']]} />{s.data && <b style={{ fontWeight: 600 }}>{s.data.period}</b>}
      <button className="btn ghost sm" style={{ marginLeft: 'auto' }} onClick={() => setSpend(true)}>Внести расходы на рекламу</button><button className="btn ghost sm" onClick={exp}><Icon name="dl" />{t('common.excel')}</button></div>
    <View s={s}>{(r) => <>
      <div className="grid kpis" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <Kpi label="Лиды" value={r.totals.leads} sub={`из них ${r.totals.ai_share_pct} % обработал ассистент`} />
        <Kpi label="Консультации" value={r.totals.consultations} sub={`конверсия ${r.totals.leads ? Math.round(r.totals.consultations / r.totals.leads * 100) : 0} %`} />
        <Kpi label="Договоры" value={r.totals.contracts} sub={`конверсия из консультации ${r.totals.consultations ? Math.round(r.totals.contracts / r.totals.consultations * 100) : 0} %`} />
        <Kpi label="Стоимость клиента" value={r.totals.cost_per_client != null ? money(r.totals.cost_per_client) : '—'} sub={`расход на рекламу ${money(r.totals.spend)}`} /></div>
      <div className="grid" style={{ gridTemplateColumns: '1.4fr 1fr', marginTop: 14 }}>
        <div className="card np"><h3 style={{ padding: '14px 16px 0' }}>По каналам и кампаниям</h3>{r.rows.length === 0 ? <Empty /> : <table className="nw"><thead><tr><th>Канал / кампания</th><th>Расход</th><th>Лиды</th><th>Консульт.</th><th>Договоры</th><th>Оплаты</th><th>Цена лида</th><th>Цена клиента</th></tr></thead><tbody>
          {r.rows.map((x, i) => <tr key={i}><td><ChTag c={x.channel} /> <span style={{ marginLeft: 4 }}>{x.campaign || '—'}</span></td><td>{x.spend ? num(x.spend) : '—'}</td><td>{x.leads}</td><td>{x.consultations}</td><td><b style={{ fontWeight: 600 }}>{x.contracts}</b></td><td>{x.paid_amount ? num(x.paid_amount) : '—'}</td><td className="muted">{x.cost_per_lead != null ? num(x.cost_per_lead) : '—'}</td><td>{x.cost_per_client != null ? num(x.cost_per_client) : '—'}</td></tr>)}</tbody></table>}</div>
        <div><div className="card"><h3>Воронка</h3>{r.funnel.map((f) => <div key={f.name} className="fun"><div style={{ width: 120 }} className="small">{f.name}</div><div className="bar"><i style={{ width: `${Math.max(f.pct, 12)}%` }}>{f.count}</i></div></div>)}</div>
          <div className="card" style={{ marginTop: 14 }}><h3>Причины отказа</h3>{r.refusals.length === 0 ? <Empty text="Отказов нет" /> : r.refusals.map((x) => <div key={x.name} className="row" style={{ justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}><span>{x.name}</span><b style={{ fontWeight: 600 }}>{x.count}</b></div>)}</div></div>
      </div></>}</View>
    {spend && <SpendModal onClose={() => setSpend(false)} onDone={() => { setSpend(false); s.reload(true); }} />}
  </>;
}

function SpendModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const d = new Date(); const [v, setV] = useState({ month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, channel: 'g', campaign: '', amount: '' });
  return <Modal small onClose={onClose}><h2>Расходы на рекламу</h2><div className="fg">
    <div><div className="lbl">Месяц</div><input className="fld" type="month" value={v.month} onChange={(e) => setV({ ...v, month: e.target.value })} /></div>
    <div><div className="lbl">Канал</div><select className="fld" value={v.channel} onChange={(e) => setV({ ...v, channel: e.target.value })}><option value="g">Google</option><option value="meta">Meta</option><option value="wa">WhatsApp</option><option value="ph">Телефония</option></select></div>
    <div><div className="lbl">Кампания</div><input className="fld" value={v.campaign} onChange={(e) => setV({ ...v, campaign: e.target.value })} placeholder="Название кампании" /></div>
    <div><div className="lbl">Сумма, сом</div><input className="fld" type="number" value={v.amount} onChange={(e) => setV({ ...v, amount: e.target.value })} /></div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" onClick={async () => { if (!v.amount) return; try { await post('reports/ad-spend/', { ...v, amount: Number(v.amount) }); toast('Расход сохранён'); onDone(); } catch (e) { toastErr(e); } }}>{t('common.save')}</button></div>
  </Modal>;
}
