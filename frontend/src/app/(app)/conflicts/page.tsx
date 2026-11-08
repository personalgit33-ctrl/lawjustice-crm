'use client';
import { useState } from 'react';
import Link from 'next/link';
import { get, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { Empty, Loading, View, useLoad } from '@/components/ui';
import { toast, toastErr } from '@/components/toast';
import { dt } from '@/lib/format';
import { isManager } from '@/lib/access';
import type { ConflictCheck } from '@/lib/types';

export default function ConflictsPage() {
  const { user } = useApp();
  const pending = useLoad(() => get<ConflictCheck[]>('conflicts/?status=pending'));
  const [cur, setCur] = useState<ConflictCheck | null>(null);
  const [q, setQ] = useState(''); const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState('');
  const check = async () => {
    const v = q.trim(); if (!v) return; setBusy(true);
    const digits = v.replace(/\D/g, '');
    const body = /^[\d\s+()-]+$/.test(v) ? (v.startsWith('+') || digits.length <= 12 ? { phone: v } : { pin: v }) : { name: v };
    try { setCur(await post<ConflictCheck>('conflicts/check/', body)); setComment(''); toast('Проверка выполнена по клиентам, противным сторонам и участникам дел'); } catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  const decide = async (decision: 'cleared' | 'refused') => {
    if (!cur) return; if (!comment.trim()) { toast('Комментарий к решению обязателен', true); return; }
    try { const r = await post<ConflictCheck>(`conflicts/${cur.id}/decide/`, { decision, comment }); setCur(r); pending.reload(true);
      toast(decision === 'refused' ? 'Отказ зафиксирован: причина «Конфликт интересов»' : 'Решение «Конфликта нет» записано в журнал'); } catch (e) { toastErr(e); }
  };
  return <div className="grid gside">
    <div>
      <div className="card"><h3>Проверить лицо</h3>
        <div className="cmd"><input className="fld" placeholder="ФИО, наименование организации, ПИН / ИНН или телефон" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && check()} /><button className="btn" onClick={check} disabled={busy}><Icon name="search" />Проверить</button></div>
        <div className="muted small" style={{ marginTop: 8 }}>Поиск по клиентам, противным сторонам и участникам всех дел, включая архив. Проверка запускается автоматически при создании лида, клиента и дела.</div></div>
      {busy && <Loading />}
      {cur && <div className="card np" style={{ marginTop: 14 }}>
        <div className="ch" style={{ padding: '14px 16px 0' }}><h3>Результат · {cur.subject_label}</h3>
          {cur.matches.length ? <span className="tag r" style={{ marginLeft: 'auto' }}>Найдено совпадений: {cur.matches.length}</span> : <span className="tag g" style={{ marginLeft: 'auto' }}>Совпадений нет</span>}</div>
        {cur.matches.length > 0 && <table><thead><tr><th>Совпадение</th><th>Роль в деле</th><th>Дело</th><th>Ответственный</th><th>Основание</th></tr></thead><tbody>
          {cur.matches.map((m, i) => <tr key={i}><td><b style={{ fontWeight: 500 }}>{m.party_name}</b></td><td><span className="tag">{m.role_label}</span></td>
            <td>{m.case_id ? <Link className="lnk" href={`/cases/${m.case_id}`}>№ {m.case_number} · {m.case_title}</Link> : '—'}<div className="muted small">Клиент: {m.client_name}</div></td><td>{m.responsible_name || '—'}</td><td className="small muted">{m.basis}</td></tr>)}</tbody></table>}
        {cur.matches.length > 0 && <div style={{ padding: '14px 16px', borderTop: '1px solid var(--border)' }}>
          {cur.status === 'pending' ? (isManager(user.role) ? <>
            <div className="lbl">Решение руководителя</div><textarea className="fld" rows={2} placeholder="Комментарий к решению (обязательно)" value={comment} onChange={(e) => setComment(e.target.value)} />
            <div className="row wrap" style={{ marginTop: 10 }}><button className="btn red sm" onClick={() => decide('refused')}>Отказать клиенту</button><button className="btn ghost sm" onClick={() => decide('cleared')}>Конфликта нет</button><span className="muted small" style={{ marginLeft: 'auto' }}>Решение и комментарий сохраняются в журнале</span></div>
          </> : <div className="note w"><Icon name="alert" /><div>Решение принимает руководитель. Карточка заблокирована до его решения.</div></div>)
            : <div className={`note ${cur.status === 'refused' ? 'r' : ''}`}><Icon name={cur.status === 'refused' ? 'x' : 'ok'} /><div><b>{cur.status === 'refused' ? 'Отказ клиенту' : cur.status === 'cleared' ? 'Конфликта нет' : 'Совпадений нет'}</b>{cur.decided_by_name && ` · ${cur.decided_by_name}, ${dt(cur.decided_at)}`}{cur.decision_comment && <div>{cur.decision_comment}</div>}</div></div>}
        </div>}
      </div>}
    </div>
    <div>
      <div className="card"><h3>Ожидают решения</h3>
        <View s={pending}>{(list) => list.length === 0 ? <Empty text="Нет проверок, ожидающих решения" /> : <>{list.map((p) => <div key={p.id} className="row" style={{ padding: '8px 0', cursor: 'pointer', borderBottom: '1px solid var(--border)' }} onClick={() => { setCur(p); setComment(''); }}>
          <div style={{ flex: 1 }}><div style={{ fontWeight: 500 }}>{p.subject_label}</div><div className="muted small">{p.source_label} · {dt(p.created_at)}</div></div><span className="tag r">Совпадение</span></div>)}</>}</View></div>
      <div className="card" style={{ marginTop: 14 }}><h3>Правила</h3><div className="small" style={{ lineHeight: 1.7, color: 'var(--tag-neutral-text)' }}>Пока проверка не завершена, карточку нельзя перевести в «Договор подписан», а дело — в «В работе».<br />Ассистент не принимает решений по конфликту и не сообщает клиенту сведения о других клиентах.<br />Проверка учитывает варианты написания ФИО.</div></div>
    </div>
  </div>;
}
