'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { get } from '@/lib/api';
import { useLoad, View, Kpi, ChTag, Ava, DueTag, Empty } from '@/components/ui';
import { Icon } from '@/components/Icon';
import { useEvents } from '@/lib/ws';
import { money } from '@/lib/format';
import type { Dashboard } from '@/lib/types';
import { Resp } from '@/components/common';

const fmtSec = (s: number) => s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${s % 60} с`;

export default function DashboardPage() {
  const s = useLoad(() => get<Dashboard>('dashboard/'));
  const router = useRouter();
  useEvents((e) => { if (['message.new', 'card.moved', 'call.updated'].includes(e.type)) s.reload(true); });
  return <View s={s}>{(d) => {
    const k = d.kpis; const diff = k.new_today - k.new_yesterday;
    const maxCh = Math.max(1, ...d.channels.map((c) => c.count));
    return <>
      <div className="grid kpis">
        <Kpi label="Новые обращения сегодня" value={k.new_today} sub={`${diff >= 0 ? '+' : ''}${diff} к вчерашнему дню`} cls={diff >= 0 ? 'up' : 'dn'} />
        <Kpi label="Первый ответ клиенту" value={fmtSec(k.first_response_sec)} sub="норматив — до 5 мин" cls={k.first_response_sec <= 300 ? 'up' : 'dn'} />
        <Kpi label="Активные дела" value={k.active_cases} sub={`${k.cases_deadline_week} со сроком на этой неделе`} />
        <Kpi label="Поступления за месяц" value={money(k.received_month)} sub={`${k.received_growth_pct >= 0 ? '+' : ''}${k.received_growth_pct} % к прошлому месяцу`} cls={k.received_growth_pct >= 0 ? 'up' : 'dn'} />
        <Kpi label="Дебиторская задолженность" value={money(k.receivables)} sub={`${k.overdue_payments} платежа просрочены`} cls={k.overdue_payments ? 'dn' : ''} />
      </div>
      <div className="grid g21" style={{ marginTop: 14 }}>
        <div className="card np"><div className="ch" style={{ padding: '14px 16px 0' }}><h3>Сроки: ближайшие и просроченные</h3><Link className="btn ghost sm" style={{ marginLeft: 'auto' }} href="/deadlines">Все сроки</Link></div>
          {d.deadlines.length === 0 ? <Empty text="Ближайших сроков нет" /> :
          <table><thead><tr><th>Срок</th><th>Событие</th><th>Дело</th><th>Ответственный</th><th></th></tr></thead><tbody>
            {d.deadlines.map((x) => <tr key={x.id} className="click" onClick={() => x.case && router.push(`/cases/${x.case}`)}><td style={{ whiteSpace: 'nowrap' }}>{x.due_label}</td><td><b style={{ fontWeight: 500 }}>{x.title}</b></td><td className="muted">{x.case_label}{x.is_confidential && <> <Icon name="lock" size={12} /></>}</td><td><Resp id={x.responsible} /></td><td><DueTag s={x.state} /></td></tr>)}
          </tbody></table>}
        </div>
        <div className="card"><h3>Требуют внимания</h3>
          {d.attention.length === 0 ? <Empty text="Всё под контролем" /> : d.attention.map((r, i) => <div key={i} className="row" style={{ padding: '9px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => r.link && router.push(r.link)}>
            <span className={`tag ${r.level}`} style={{ width: 8, height: 8, padding: 0, borderRadius: '50%' }} /><div style={{ flex: 1 }}><div style={{ fontWeight: 500 }}>{r.title}</div><div className="muted small">{r.text}</div></div><Icon name="arrow" style={{ color: 'var(--text-muted)' }} /></div>)}
          {(d.missed_calls > 0 || d.stale_items > 0) && <div className="muted small" style={{ marginTop: 10 }}>Пропущенных звонков: {d.missed_calls} · Без движения дольше срока: {d.stale_items}</div>}
        </div>
      </div>
      <div className="grid g3" style={{ marginTop: 14 }}>
        <div className="card"><h3>Обращения по каналам · неделя</h3>{d.channels.map((r) => <div key={r.channel} className="row" style={{ margin: '9px 0' }}><div style={{ width: 110 }}><ChTag c={r.channel} /></div><div className="bar" style={{ flex: 1 }}><i style={{ width: `${(r.count / maxCh) * 100}%` }} /></div><b style={{ width: 28, textAlign: 'right', fontWeight: 600 }}>{r.count}</b></div>)}</div>
        <div className="card"><h3>Загрузка юристов</h3>{d.workload.length === 0 ? <Empty /> : d.workload.map((w) => <div key={w.user} className="row" style={{ margin: '8px 0' }}><Ava initials={w.initials} name={w.name} /><div style={{ width: 130, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name}</div><div className="bar" style={{ flex: 1 }}><i style={{ width: `${w.pct}%` }} /></div><span className="muted small" style={{ width: 48, textAlign: 'right' }}>{w.cases} дел</span></div>)}</div>
        <div className="card"><h3>Первая линия · неделя</h3>{([['Обработано ассистентом без участия сотрудника', `${d.first_line.ai_share_pct} %`], ['Передано сотрудникам', `${d.first_line.handed_pct} %`], ['Записано на консультацию', d.first_line.consultations], ['Ответы ассистента отмечены «неверно»', d.first_line.ai_wrong]] as [string, any][]).map((r) => <div key={r[0]} className="row" style={{ justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--border)' }}><span className="muted">{r[0]}</span><b style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{r[1]}</b></div>)}</div>
      </div>
    </>;
  }}</View>;
}

