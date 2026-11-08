'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { get } from '@/lib/api';
import { Icon } from '@/components/Icon';
import { Ava, Empty, Seg, View, useLoad } from '@/components/ui';
import { CaseForm } from '@/components/CaseForm';
import { useApp } from '@/components/AppContext';
import type { Case } from '@/lib/types';

type F = 'all' | 'mine' | 'court' | 'waiting' | 'archived';
export default function CasesPage() {
  const router = useRouter(); const { userById } = useApp();
  const [f, setF] = useState<F>('all'); const [q, setQ] = useState(''); const [dq, setDq] = useState(''); const [add, setAdd] = useState(false);
  useEffect(() => { const h = setTimeout(() => setDq(q), 300); return () => clearTimeout(h); }, [q]);
  const qs = `cases/?search=${encodeURIComponent(dq)}${f === 'mine' ? '&mine=1' : f === 'court' ? '&court=1' : f === 'waiting' ? '&status=waiting' : f === 'archived' ? '&archived=1' : ''}`;
  const s = useLoad(() => get<Case[]>(qs), [qs]);
  return <>
    <div className="bhead"><Seg value={f} onChange={setF} options={[['all', 'Все'], ['mine', 'Мои'], ['court', 'В суде'], ['waiting', 'Ожидание клиента'], ['archived', 'Архив']]} />
      <input className="fld" style={{ width: 260 }} placeholder="№ дела, клиент, противная сторона" value={q} onChange={(e) => setQ(e.target.value)} />
      <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => setAdd(true)}><Icon name="plus" />Дело</button></div>
    <View s={s}>{(list) => list.length === 0 ? <div className="card"><Empty text="Дел не найдено" /></div> : <div className="card np"><table><thead><tr><th>№</th><th>Наименование</th><th>Клиент</th><th>Противная сторона</th><th>Категория</th><th>Статус</th><th>Юрист</th><th>Инстанция</th><th>Ближайший срок</th></tr></thead><tbody>
      {list.map((c) => { const u = userById(c.responsible); return <tr key={c.id} className="click" onClick={() => router.push(`/cases/${c.id}`)}>
        <td className="muted" style={{ whiteSpace: 'nowrap' }}>{c.number}</td>
        <td><b style={{ fontWeight: 500 }}>{c.restricted ? 'Материалы скрыты' : c.title}</b>{c.is_confidential && <> <span className="tag" title="Конфиденциальное дело: доступ только участникам"><Icon name="lock" size={11} />Конфиденциально</span></>}{c.stale && <> <span className="tag a">Без движения</span></>}{c.conflict_status === 'hit' && <> <span className="tag r">Конфликт</span></>}</td>
        <td>{c.client_name}</td><td className="muted">{c.opponents || '—'}</td><td>{c.category}</td><td><span className="tag b">{c.status_label}</span></td>
        <td>{u ? <Ava initials={u.initials} name={u.full_name} /> : '—'}</td><td className="small">{c.court || '—'}</td>
        <td>{c.nearest_deadline ? <span className={`due ${c.nearest_deadline_state === 'late' ? 'late' : c.nearest_deadline_state === 'today' || c.nearest_deadline_state === 'week' ? 'soon' : ''}`}>{new Date(c.nearest_deadline).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</span> : '—'}</td></tr>; })}
    </tbody></table></div>}</View>
    {add && <CaseForm onClose={() => setAdd(false)} onDone={(c) => { setAdd(false); router.push(`/cases/${c.id}`); }} />}
  </>;
}
