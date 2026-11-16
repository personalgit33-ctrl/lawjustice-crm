'use client';
import { useEffect, useState } from 'react';
import { get, post } from '@/lib/api';
import { useApp } from './AppContext';
import { Icon } from './Icon';
import { Modal } from './ui';
import { UserSelect } from './common';
import { toast, toastErr } from './toast';
import { t } from '@/i18n';
import type { Case, Client, Party } from '@/lib/types';

export function CaseForm({ onClose, onDone, clientId }: { onClose: () => void; onDone: (c: Case) => void; clientId?: number }) {
  const { dict, user, users } = useApp();
  const [clients, setClients] = useState<Client[]>([]); const [cq, setCq] = useState('');
  const [v, setV] = useState({ title: '', client: clientId ?? null as number | null, category: dict.case_category[0]?.name || '', responsible: user.role === 'lawyer' ? user.id : null as number | null, court: '', is_confidential: false, members: [] as number[] });
  const [parties, setParties] = useState<Pick<Party, 'role' | 'name' | 'pin' | 'phone'>[]>([{ role: 'opponent', name: '', pin: '', phone: '' }]);
  useEffect(() => { const h = setTimeout(() => get<Client[]>(`clients/?search=${encodeURIComponent(cq)}`).then((x) => setClients(x.slice(0, 30))).catch(() => {}), 250); return () => clearTimeout(h); }, [cq]);
  const save = async () => {
    if (!v.title.trim() || !v.client) { toast('Укажите наименование и клиента', true); return; }
    try {
      const c = await post<Case>('cases/', { ...v, parties: parties.filter((p) => p.name.trim()) });
      toast(c.conflict_status === 'hit' ? `Дело № ${c.number} создано. Найден конфликт интересов — требуется решение руководителя` : `Дело № ${c.number} создано`, c.conflict_status === 'hit'); onDone(c);
    } catch (e: any) { toast(e.message, true); }
  };
  return <Modal onClose={onClose}><h2>Новое дело</h2>
    <div className="fg">
      <div className="full"><div className="lbl">Наименование</div><input className="fld" autoFocus value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} placeholder="Например: раздел имущества" /></div>
      <div><div className="lbl">Клиент</div><input className="fld" placeholder="Поиск клиента" value={cq} onChange={(e) => setCq(e.target.value)} style={{ marginBottom: 4 }} />
        <select className="fld" value={v.client ?? ''} onChange={(e) => setV({ ...v, client: e.target.value ? Number(e.target.value) : null })}><option value="">Выберите клиента</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.phone}</option>)}</select></div>
      <div><div className="lbl">Категория</div><select className="fld" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>{dict.case_category.map((x) => <option key={x.id}>{x.name}</option>)}</select>
        <div className="lbl" style={{ marginTop: 8 }}>Ответственный юрист</div><UserSelect value={v.responsible} onChange={(x) => setV({ ...v, responsible: x })} filter={(u) => u.role === 'lawyer' || u.role === 'manager'} /></div>
      <div><div className="lbl">Суд / инстанция</div><input className="fld" value={v.court} onChange={(e) => setV({ ...v, court: e.target.value })} /></div>
      <div><div className="lbl">Участники дела (доступ)</div><div className="picker">{users.filter((u) => u.is_active && u.role !== 'ai').map((u) => <button key={u.id} className={v.members.includes(u.id) ? 'on' : ''} onClick={() => setV({ ...v, members: v.members.includes(u.id) ? v.members.filter((x) => x !== u.id) : [...v.members, u.id] })}>{u.full_name.split(' ')[0]}</button>)}</div></div>
      <label className="full chk"><input type="checkbox" checked={v.is_confidential} onChange={(e) => setV({ ...v, is_confidential: e.target.checked })} /> Конфиденциальное дело — видят только участники и руководитель, ассистент отключён</label>
      <div className="full"><div className="lbl">Стороны (противная сторона, третьи лица) — для проверки конфликта интересов</div>
        {parties.map((p, i) => <div key={i} className="row" style={{ marginBottom: 6 }}>
          <select className="fld" style={{ width: 160 }} value={p.role} onChange={(e) => setParties(parties.map((x, j) => j === i ? { ...x, role: e.target.value as any } : x))}><option value="opponent">Противная сторона</option><option value="third">Третье лицо</option></select>
          <input className="fld" placeholder="ФИО / наименование" value={p.name} onChange={(e) => setParties(parties.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
          <input className="fld" style={{ width: 140 }} placeholder="ПИН / ИНН" value={p.pin} onChange={(e) => setParties(parties.map((x, j) => j === i ? { ...x, pin: e.target.value } : x))} />
          <input className="fld" style={{ width: 150 }} placeholder="Телефон" value={p.phone} onChange={(e) => setParties(parties.map((x, j) => j === i ? { ...x, phone: e.target.value } : x))} />
          <button className="ib" onClick={() => setParties(parties.filter((_, j) => j !== i))}><Icon name="x" /></button></div>)}
        <button className="btn ghost sm" onClick={() => setParties([...parties, { role: 'opponent', name: '', pin: '', phone: '' }])}><Icon name="plus" />Сторона</button></div>
    </div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button><button className="btn" onClick={save}>{t('common.create')}</button></div>
  </Modal>;
}
