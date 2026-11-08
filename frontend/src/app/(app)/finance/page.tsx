'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { download, get, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { Ava, Empty, Kpi, Modal, View, useLoad } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { money, num, ymd } from '@/lib/format';
import { isManager } from '@/lib/access';
import { t } from '@/i18n';
import type { Case, Client, Contract, FinanceSummary, Payment } from '@/lib/types';

export default function FinancePage() {
  const { user, userById } = useApp();
  const sum = useLoad(() => get<FinanceSummary>('finance/summary/'));
  const s = useLoad(() => get<Contract[]>('contracts/'));
  const [open, setOpen] = useState<Contract | null>(null);
  const [add, setAdd] = useState(false);
  const reload = () => { s.reload(true); sum.reload(true); };
  const exp = async () => { try { await download('finance/export/', 'finance.xlsx'); toast('Отчёт выгружен в Excel'); } catch (e) { toastErr(e); } };
  const growth = sum.data && sum.data.received_prev_month ? Math.round((sum.data.received_month / sum.data.received_prev_month - 1) * 100) : null;
  return <>
    <View s={sum}>{(f) => <div className="grid kpis" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
      <Kpi label="Поступления за месяц" value={money(f.received_month)} sub={growth != null ? `${growth >= 0 ? '+' : ''}${growth} % к прошлому месяцу` : ''} cls={growth != null && growth >= 0 ? 'up' : 'dn'} />
      <Kpi label="Ожидается в следующем месяце" value={money(f.expected_next)} sub="по графикам платежей" />
      <Kpi label="Дебиторская задолженность" value={money(f.receivables)} sub={`${f.overdue_count} платежа просрочены`} cls={f.overdue_count ? 'dn' : ''} />
      <Kpi label="Договоров подписано" value={f.contracts_signed} sub={`средний гонорар ${money(f.avg_fee)}`} /></div>}</View>
    <div className="card np" style={{ marginTop: 14 }}><div className="ch" style={{ padding: '14px 16px 0' }}><h3>Договоры и расчёты с клиентами</h3>
      <div className="row" style={{ marginLeft: 'auto' }}>{isManager(user.role) && <button className="btn ghost sm" onClick={exp}><Icon name="dl" />{t('common.excel')}</button>}<button className="btn sm" onClick={() => setAdd(true)}><Icon name="plus" />Договор</button></div></div>
      <View s={s}>{(list) => list.length === 0 ? <Empty text="Договоров нет" /> : <table><thead><tr><th>Клиент / дело</th><th>Договор</th><th>Модель оплаты</th><th>Гонорар</th><th>Оплачено</th><th>Долг</th><th>Следующий платёж</th><th>Ответственный</th></tr></thead><tbody>
        {list.map((c) => { const u = userById(c.responsible); return <tr key={c.id} className="click" onClick={() => setOpen(c)}><td><b style={{ fontWeight: 500 }}>{c.client_name}{c.case_number && ` · ${c.case_number}`}</b></td>
          <td>{c.status === 'signed' ? <span className="tag g">{t('contract.signed')}</span> : c.status === 'sent' ? <span className="tag a">{t('contract.sent')}</span> : <span className="tag">{t('contract.none')}</span>}</td>
          <td className="muted">{c.model_label}</td><td>{num(c.fee)}</td><td>{num(c.paid)}</td><td style={c.debt > 0 ? { color: 'var(--danger)', fontWeight: 600 } : undefined}>{num(c.debt)}</td>
          <td>{c.next_payment_overdue ? <span className="tag r">{c.next_payment_label}</span> : c.next_payment_label || '—'}</td><td>{u ? <Ava initials={u.initials} name={u.full_name} /> : '—'}</td></tr>; })}
      </tbody></table>}</View></div>
    <View s={sum}>{(f) => <div className="card" style={{ marginTop: 14 }}><h3>Выручка по направлениям</h3>{f.by_category.length === 0 ? <Empty /> : f.by_category.map((r) => <div key={r.name} className="row" style={{ margin: '9px 0' }}><div style={{ width: 170 }}>{r.name}</div><div className="bar" style={{ flex: 1 }}><i style={{ width: `${r.share}%` }} /></div><b style={{ width: 110, textAlign: 'right', fontWeight: 600 }}>{r.share} % · {num(r.amount)}</b></div>)}</div>}</View>
    {open && <ContractModal c={open} onClose={() => setOpen(null)} onChanged={(c) => { setOpen(c); reload(); }} />}
    {add && <NewContract onClose={() => setAdd(false)} onDone={() => { setAdd(false); reload(); }} />}
  </>;
}

function ContractModal({ c, onClose, onChanged }: { c: Contract; onClose: () => void; onChanged: (c: Contract) => void }) {
  const pay = async (p: Payment) => {
    const v = prompt(`Сумма оплаты (к оплате ${num(p.amount - p.paid_amount)} сом)`, String(p.amount - p.paid_amount)); if (!v) return;
    try { await post(`payments/${p.id}/pay/`, { amount: Number(v.replace(/\s/g, '')), paid_at: ymd(new Date()) }); onChanged(await get<Contract>(`contracts/${c.id}/`)); toast('Оплата отмечена'); } catch (e) { toastErr(e); }
  };
  return <Modal onClose={onClose}><h2>Договор · {c.client_name}{c.case_number && ` · № ${c.case_number}`}</h2>
    <div className="kv"><span>Статус</span><div>{t('contract.' + c.status)}</div><span>Модель</span><div>{c.model_label}</div><span>Гонорар</span><div>{money(c.fee)}</div><span>Оплачено</span><div>{money(c.paid)}</div><span>Долг</span><div style={c.debt ? { color: 'var(--danger)', fontWeight: 600 } : undefined}>{money(c.debt)}</div>
      {c.case && <><span>Дело</span><Link className="lnk" href={`/cases/${c.case}`}>№ {c.case_number}</Link></>}</div>
    <h3>График платежей</h3>
    {c.payments.length === 0 ? <Empty text="График не задан" /> : <table><thead><tr><th>Дата</th><th>Сумма</th><th>Оплачено</th><th>Статус</th><th></th></tr></thead><tbody>
      {c.payments.map((p) => <tr key={p.id}><td>{new Date(p.due_date).toLocaleDateString('ru-RU')}</td><td>{num(p.amount)}</td><td>{num(p.paid_amount)}</td>
        <td>{p.paid_amount >= p.amount ? <span className="tag g">Оплачено</span> : p.overdue_days > 0 ? <span className="tag r">Просрочен {p.overdue_days} дн.</span> : <span className="tag">Ожидается</span>}</td>
        <td>{p.paid_amount < p.amount && <button className="btn ghost sm" onClick={() => pay(p)}><Icon name="ok" />Отметить оплату</button>}</td></tr>)}</tbody></table>}
  </Modal>;
}

function NewContract({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { user } = useApp();
  const [clients, setClients] = useState<Client[]>([]); const [cases, setCases] = useState<Case[]>([]);
  const [v, setV] = useState({ client: null as number | null, case: null as number | null, status: 'sent', model: 'fixed', fee: '', responsible: user.id as number | null });
  const [pays, setPays] = useState<{ due_date: string; amount: string }[]>([{ due_date: ymd(new Date()), amount: '' }]);
  useEffect(() => { get<Client[]>('clients/').then(setClients).catch(() => {}); get<Case[]>('cases/').then(setCases).catch(() => {}); }, []);
  const save = async () => {
    if (!v.client || !v.fee) { toast('Укажите клиента и сумму гонорара', true); return; }
    try { await post('contracts/', { ...v, fee: Number(v.fee), payments: pays.filter((p) => p.amount).map((p) => ({ due_date: p.due_date, amount: Number(p.amount) })) }); toast('Договор создан'); onDone(); } catch (e) { toastErr(e); }
  };
  return <Modal small onClose={onClose}><h2>Новый договор</h2><div className="fg">
    <div className="full"><div className="lbl">Клиент</div><select className="fld" value={v.client ?? ''} onChange={(e) => setV({ ...v, client: e.target.value ? Number(e.target.value) : null, case: null })}><option value="">—</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
    <div className="full"><div className="lbl">Дело</div><select className="fld" value={v.case ?? ''} onChange={(e) => setV({ ...v, case: e.target.value ? Number(e.target.value) : null })}><option value="">—</option>{cases.filter((c) => !v.client || c.client === v.client).map((c) => <option key={c.id} value={c.id}>№ {c.number} · {c.title}</option>)}</select></div>
    <div><div className="lbl">Статус</div><select className="fld" value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}><option value="none">Не заключён</option><option value="sent">Отправлен</option><option value="signed">Подписан</option></select></div>
    <div><div className="lbl">Модель оплаты</div><select className="fld" value={v.model} onChange={(e) => setV({ ...v, model: e.target.value })}><option value="fixed">Фиксированная</option><option value="staged">Поэтапная</option><option value="subscription">Абонентская</option></select></div>
    <div><div className="lbl">Гонорар, сом</div><input className="fld" type="number" value={v.fee} onChange={(e) => setV({ ...v, fee: e.target.value })} /></div>
    <div><div className="lbl">Ответственный</div><UserSelect value={v.responsible} onChange={(x) => setV({ ...v, responsible: x })} /></div>
    <div className="full"><div className="lbl">График платежей</div>{pays.map((p, i) => <div key={i} className="row" style={{ marginBottom: 6 }}><input className="fld" type="date" value={p.due_date} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, due_date: e.target.value } : x))} /><input className="fld" type="number" placeholder="Сумма" value={p.amount} onChange={(e) => setPays(pays.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} /><button className="ib" onClick={() => setPays(pays.filter((_, j) => j !== i))}><Icon name="x" /></button></div>)}
      <button className="btn ghost sm" onClick={() => setPays([...pays, { due_date: ymd(new Date()), amount: '' }])}><Icon name="plus" />Платёж</button></div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button><button className="btn" onClick={save}>{t('common.create')}</button></div>
  </Modal>;
}
