'use client';
import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { get, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { Empty, Modal, Seg, View, useLoad } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { fromLocalInput, time, ymd } from '@/lib/format';
import { t } from '@/i18n';
import type { CalendarItem } from '@/lib/types';

type M = 'day' | 'week' | 'month';
const COL: Record<CalendarItem['kind'], string> = { hearing: 'var(--danger)', deadline: 'var(--warning)', consultation: 'var(--primary)', meeting: 'var(--primary)', card: 'var(--label-gray)' };
const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

export default function CalendarPage() {
  const router = useRouter(); const { user } = useApp();
  const [mode, setMode] = useState<M>('month');
  const [cur, setCur] = useState(() => new Date());
  const [mine, setMine] = useState(user.role === 'lawyer');
  const [add, setAdd] = useState(false);
  const range = useMemo(() => {
    const s = new Date(cur); s.setHours(0, 0, 0, 0);
    if (mode === 'month') { s.setDate(1); const wd = (s.getDay() + 6) % 7; s.setDate(1 - wd); const e = new Date(s); e.setDate(s.getDate() + 41); return [s, e]; }
    if (mode === 'week') { const wd = (s.getDay() + 6) % 7; s.setDate(s.getDate() - wd); const e = new Date(s); e.setDate(s.getDate() + 6); return [s, e]; }
    return [s, new Date(s)];
  }, [cur, mode]);
  const s = useLoad(() => get<CalendarItem[]>(`calendar/?from=${ymd(range[0])}&to=${ymd(range[1])}`), [range[0].getTime(), range[1].getTime()]);
  const shift = (n: number) => { const d = new Date(cur); if (mode === 'month') d.setMonth(d.getMonth() + n); else d.setDate(d.getDate() + n * (mode === 'week' ? 7 : 1)); setCur(d); };
  const today = ymd(new Date());
  const items = (s.data || []).filter((i) => !mine || i.user_id === user.id);
  const of = (d: Date) => items.filter((i) => ymd(new Date(i.start)) === ymd(d)).sort((a, b) => a.start.localeCompare(b.start));
  const days = Array.from({ length: Math.round((range[1].getTime() - range[0].getTime()) / 86400000) + 1 }, (_, i) => { const d = new Date(range[0]); d.setDate(d.getDate() + i); return d; });
  const ev = (i: CalendarItem) => <span key={i.id} className="ev" style={{ borderColor: COL[i.kind] }} title={i.title} onClick={() => i.link && router.push(i.link)}>{i.kind !== 'deadline' && !i.start.endsWith('T00:00:00Z') ? time(i.start) + ' ' : ''}{i.title}</span>;
  const label = mode === 'month' ? cur.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }) : mode === 'week' ? `${range[0].toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} — ${range[1].toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })}` : cur.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
  return <>
    <div className="bhead"><Seg value={mode} onChange={setMode} options={[['day', 'День'], ['week', 'Неделя'], ['month', 'Месяц']]} />
      <button className="btn ghost sm" onClick={() => shift(-1)}><Icon name="left" /></button><button className="btn ghost sm" onClick={() => setCur(new Date())}>Сегодня</button><button className="btn ghost sm" onClick={() => shift(1)}><Icon name="arrow" /></button>
      <b style={{ fontWeight: 600, textTransform: 'capitalize' }}>{label}</b>
      <label className="chk small"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />Только мои</label>
      <div className="row wrap" style={{ marginLeft: 'auto' }}>{([['var(--danger)', 'Заседания'], ['var(--warning)', 'Сроки'], ['var(--primary)', 'Консультации и встречи']] as const).map((x) => <span key={x[1]} className="tag o"><i style={{ background: x[0] }} />{x[1]}</span>)}
        <button className="btn sm" onClick={() => setAdd(true)}><Icon name="plus" />Событие</button></div></div>
    <View s={s}>{() => mode === 'day' ? <div className="card np dayv">{of(cur).length === 0 ? <Empty text="Событий нет" /> : of(cur).map((i) => <div key={i.id} className="slot" style={{ cursor: 'pointer' }} onClick={() => i.link && router.push(i.link)}><b>{time(i.start)}</b><span className="tag o"><i style={{ background: COL[i.kind] }} /></span><div>{i.title}</div></div>)}</div> :
      <div className="cal">{WD.map((x) => <div key={x} className="dh">{x}</div>)}
        {days.map((d) => { const k = ymd(d); return <div key={k} className={`${k === today ? 'today' : ''} ${mode === 'month' && d.getMonth() !== cur.getMonth() ? 'off' : ''}`} style={mode === 'week' ? { minHeight: 260 } : undefined}>
          <b style={{ fontWeight: k === today ? 700 : 500 }}>{d.getDate()}{k === today && <> <span className="tag b" style={{ fontSize: 10 }}>сегодня</span></>}</b>{of(d).map(ev)}</div>; })}</div>}</View>
    {add && <NewEvent onClose={() => setAdd(false)} onDone={() => { setAdd(false); s.reload(true); }} />}
  </>;
}

function NewEvent({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { user } = useApp();
  const [v, setV] = useState({ title: '', kind: 'consultation', start: '', end: '', user: user.id as number | null });
  return <Modal small onClose={onClose}><h2>Новое событие</h2><div className="fg">
    <div className="full"><div className="lbl">Название</div><input className="fld" autoFocus value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} /></div>
    <div><div className="lbl">Тип</div><select className="fld" value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value })}><option value="consultation">Консультация</option><option value="meeting">Встреча</option><option value="hearing">Заседание</option></select></div>
    <div><div className="lbl">Сотрудник</div><UserSelect value={v.user} onChange={(x) => setV({ ...v, user: x })} /></div>
    <div><div className="lbl">Начало</div><input type="datetime-local" className="fld" value={v.start} onChange={(e) => setV({ ...v, start: e.target.value })} /></div>
    <div><div className="lbl">Окончание</div><input type="datetime-local" className="fld" value={v.end} onChange={(e) => setV({ ...v, end: e.target.value })} /></div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" onClick={async () => { if (!v.title || !v.start) { toast('Укажите название и начало', true); return; } try { await post('events/', { ...v, start: fromLocalInput(v.start), end: v.end ? fromLocalInput(v.end) : null }); toast('Событие добавлено, напоминание настроено'); onDone(); } catch (e) { toastErr(e); } }}>{t('common.save')}</button></div>
  </Modal>;
}
