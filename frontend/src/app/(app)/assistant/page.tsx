'use client';
import { useRef, useState } from 'react';
import { get, post } from '@/lib/api';
import { Icon } from '@/components/Icon';
import { Loading, useLoad } from '@/components/ui';
import { toast, toastErr } from '@/components/toast';
import { time } from '@/lib/format';
import { t } from '@/i18n';
import type { AssistantRun } from '@/lib/types';

const EXAMPLES = [
  'Создай карточку на Айбека, уголовное дело, ответственный Бакыт, связаться сегодня',
  'Создай карточку на ОсОО «Бишкек Трейд», корпоративный спор, ответственная Айгуль, срок пятница',
  'Перенеси карточку Ивана Петрова в «Консультация назначена»',
  'Покажи просроченные задачи Бакыта',
];

export default function AssistantPage() {
  const s = useLoad(() => get<AssistantRun[]>('assistant/'));
  const [cmd, setCmd] = useState(''); const [busy, setBusy] = useState(false);
  const inp = useRef<HTMLInputElement>(null);
  const run = async (text = cmd) => {
    const q = text.trim(); if (!q) return; setBusy(true);
    try { const r = await post<AssistantRun>('assistant/command/', { text: q }); s.setData((a) => [r, ...(a || [])]); setCmd(''); inp.current?.focus(); }
    catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  const act = async (r: AssistantRun, a: 'confirm' | 'cancel') => {
    try { const n = await post<AssistantRun>(`assistant/${r.id}/${a}/`); s.setData((x) => (x || []).map((y) => y.id === r.id ? n : y)); toast(a === 'confirm' ? 'Действие выполнено' : 'Действие отменено'); } catch (e) { toastErr(e); }
  };
  return <div className="aiwrap"><div>
    <div className="card"><h3>Команда ассистенту</h3>
      <div className="cmd"><input ref={inp} className="fld" value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="Например: создай карточку на Айбека, уголовное дело, ответственный Бакыт, связаться сегодня" onKeyDown={(e) => e.key === 'Enter' && run()} disabled={busy} />
        <button className="btn" onClick={() => run()} disabled={busy}>{busy ? 'Выполняю…' : 'Выполнить'}</button></div>
      <div className="muted small" style={{ marginTop: 8 }}>Ассистент действует только через разрешённые функции CRM. Смена ответственного и перенос в итоговые колонки — после подтверждения.</div></div>
    <div style={{ marginTop: 14 }}>{s.loading && !s.data ? <Loading /> : !s.data?.length ? <div className="card muted">Результаты команд появятся здесь.</div> : s.data.map((a) => <div key={a.id} className="card" style={{ marginBottom: 12 }}>
      <div className="muted small">Команда · {time(a.created_at)}{a.engine === 'claude' ? ' · Claude' : ''}</div>
      <div style={{ fontWeight: 500, margin: '2px 0 10px' }}>{a.command}</div>
      <div className="steps">{a.steps.map((st, i) => <p key={i}><span className={`stp ${st.status === 'pending' ? 'w' : st.status === 'denied' || st.status === 'cancelled' ? 'x' : ''}`}><Icon name={st.status === 'pending' ? 'pause' : st.status === 'done' ? 'ok' : 'x'} /></span><span><b style={{ fontWeight: 500 }}>{st.label}</b>{st.detail && ` — ${st.detail}`}{st.needs_confirm && st.status === 'pending' && <span className="tag a" style={{ marginLeft: 6 }}>С подтверждением</span>}</span></p>)}</div>
      {a.state === 'awaiting_confirm' && <div className="row" style={{ marginTop: 10 }}><button className="btn sm" onClick={() => act(a, 'confirm')}>{t('common.confirm')}</button><button className="btn ghost sm" onClick={() => act(a, 'cancel')}>{t('common.cancel')}</button></div>}
      <div style={{ marginTop: 10, color: a.state === 'awaiting_confirm' ? 'var(--warning)' : a.state === 'done' ? 'var(--success)' : 'var(--danger)', fontWeight: 500 }}>{a.result}</div>
    </div>)}</div>
  </div>
  <div><div className="card sugg"><h3>Примеры команд</h3>{EXAMPLES.map((e) => <button key={e} onClick={() => { setCmd(e); run(e); }}>{e}</button>)}</div>
    <div className="card np" style={{ marginTop: 14 }}><h3 style={{ padding: '14px 16px 0' }}>Права ассистента</h3><table><tbody>
      <tr><td style={{ width: 120 }}><span className="tag g">Сам</span></td><td className="small">лид, клиент, карточка, поля, резюме, стандартная задача, запись на консультацию</td></tr>
      <tr><td><span className="tag a">С подтверждением</span></td><td className="small">смена ответственного, итоговые колонки, изменение данных клиента, массовые действия</td></tr>
      <tr><td><span className="tag r">Запрещено</span></td><td className="small">удаление, закрытие дела, финансы, юридические оценки, решения по конфликту интересов, конфиденциальные дела</td></tr>
    </tbody></table></div></div></div>;
}
