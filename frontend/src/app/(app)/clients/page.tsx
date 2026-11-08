'use client';
import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { download, get, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { ChTag, Empty, Loading, Modal, Seg, View, useLoad } from '@/components/ui';
import { Resp, UserSelect } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { t } from '@/i18n';
import type { Client } from '@/lib/types';

export default function ClientsPage() { return <Suspense fallback={<Loading />}><Clients /></Suspense>; }

function Clients() {
  const sp = useSearchParams(); const router = useRouter(); const { user } = useApp();
  const [f, setF] = useState<'all' | 'person' | 'company' | 'noconsent'>('all');
  const [q, setQ] = useState('');
  const [dq, setDq] = useState('');
  useEffect(() => { const h = setTimeout(() => setDq(q), 300); return () => clearTimeout(h); }, [q]);
  const [newC, setNewC] = useState(sp.get('new') === '1');
  const qs = `clients/?search=${encodeURIComponent(dq)}${f === 'person' || f === 'company' ? '&kind=' + f : ''}${f === 'noconsent' ? '&no_consent=1' : ''}`;
  const s = useLoad(() => get<Client[]>(qs), [qs]);
  const exp = async () => { try { await download('clients/export/', 'clients.csv'); toast('Выгрузка зафиксирована в журнале'); } catch (e: any) { toast(e.status === 403 ? 'Выгрузка доступна только администратору и фиксируется в журнале' : e.message, true); } };
  return <>
    <div className="bhead"><Seg value={f} onChange={setF} options={[['all', 'Все'], ['person', 'Физлица'], ['company', 'Юрлица'], ['noconsent', 'Без согласия ПД']]} />
      <input className="fld" style={{ width: 260 }} placeholder="Имя, телефон, email, ПИН / ИНН" value={q} onChange={(e) => setQ(e.target.value)} />
      {user.role === 'admin' && <button className="btn ghost sm" style={{ marginLeft: 'auto' }} onClick={exp}><Icon name="dl" />{t('common.export')}</button>}
      <button className="btn sm" style={user.role === 'admin' ? undefined : { marginLeft: 'auto' }} onClick={() => setNewC(true)}><Icon name="plus" />Клиент</button></div>
    <View s={s}>{(list) => list.length === 0 ? <div className="card"><Empty text="Клиентов не найдено" /></div> : <div className="card np"><table><thead><tr><th>Клиент</th><th>Тип</th><th>Телефон</th><th>Источник</th><th>Ответственный</th><th>Дела</th><th>Согласие ПД</th><th>Конфликт</th><th>Последний контакт</th></tr></thead><tbody>
      {list.map((c) => <tr key={c.id} className="click" onClick={() => router.push(`/clients/${c.id}`)}><td><b style={{ fontWeight: 500 }}>{c.name}</b>{c.city && <div className="muted small">{c.city}</div>}</td><td className="muted">{c.kind === 'company' ? 'Юрлицо' : 'Физлицо'}</td><td style={{ whiteSpace: 'nowrap' }}>{c.phone}</td><td><ChTag c={c.source} /></td>
        <td><Resp id={c.responsible} full /></td><td>{c.cases_count}</td><td>{c.consent_status === 'given' ? <span className="tag g">Получено</span> : c.consent_status === 'revoked' ? <span className="tag r">Отозвано</span> : <span className="tag a">Нет</span>}</td>
        <td>{c.conflict_status === 'hit' ? <span className="tag r">Совпадение</span> : c.conflict_status === 'refused' ? <span className="tag r">Отказ</span> : c.conflict_status === 'none' ? <span className="tag">—</span> : <span className="tag g">Нет</span>}</td><td className="muted small">{c.last_contact_label || '—'}</td></tr>)}
    </tbody></table></div>}</View>
    {newC && <ClientForm initial={{ phone: sp.get('phone') || '' }} onClose={() => setNewC(false)} onDone={(c) => { setNewC(false); router.push(`/clients/${c.id}`); }} />}
  </>;
}

function ClientForm({ initial, onClose, onDone }: { initial: Partial<Client>; onClose: () => void; onDone: (c: Client) => void }) {
  const { user } = useApp();
  const [v, setV] = useState({ kind: 'person', name: '', phone: '', email: '', city: 'Бишкек', pin: '', source: 'manual', notes: '', responsible: user.role === 'lawyer' ? user.id : null as number | null, opponent: '', ...initial });
  const set = (k: string, x: any) => setV({ ...v, [k]: x });
  const save = async () => {
    if (!v.name.trim()) { toast('Укажите имя или наименование', true); return; }
    try { const { opponent, ...body } = v as any; const c = await post<Client>('clients/', { ...body, opponents: opponent ? [opponent] : undefined });
      toast(c.conflict_status === 'hit' ? 'Клиент создан. Найдено совпадение — требуется решение руководителя' : 'Клиент создан · проверка конфликта интересов выполнена', c.conflict_status === 'hit'); onDone(c); } catch (e) { toastErr(e); }
  };
  return <Modal small onClose={onClose}><h2>Новый клиент</h2>
    <div className="fg">
      <div className="full"><Seg value={v.kind as string} onChange={(x) => set('kind', x)} options={[['person', 'Физлицо'], ['company', 'Юрлицо']]} /></div>
      <div className="full"><div className="lbl">{v.kind === 'company' ? 'Наименование' : 'ФИО'}</div><input className="fld" autoFocus value={v.name} onChange={(e) => set('name', e.target.value)} /></div>
      <div><div className="lbl">Телефон</div><input className="fld" value={v.phone} onChange={(e) => set('phone', e.target.value)} /></div>
      <div><div className="lbl">Email</div><input className="fld" value={v.email} onChange={(e) => set('email', e.target.value)} /></div>
      <div><div className="lbl">{v.kind === 'company' ? 'ИНН' : 'ПИН'}</div><input className="fld" value={v.pin} onChange={(e) => set('pin', e.target.value)} /></div>
      <div><div className="lbl">Город</div><input className="fld" value={v.city} onChange={(e) => set('city', e.target.value)} /></div>
      <div><div className="lbl">Источник</div><select className="fld" value={v.source} onChange={(e) => set('source', e.target.value)}>{['manual', 'wa', 'g', 'meta', 'ph'].map((x) => <option key={x} value={x}>{t('ch.' + x)}</option>)}</select></div>
      <div><div className="lbl">Ответственный</div><UserSelect value={v.responsible} onChange={(x) => set('responsible', x)} /></div>
      <div className="full"><div className="lbl">Противная сторона (для проверки конфликта)</div><input className="fld" value={v.opponent} onChange={(e) => set('opponent', e.target.value)} placeholder="ФИО или наименование — необязательно" /></div>
      <div className="full"><div className="lbl">Заметки</div><textarea className="fld" rows={2} value={v.notes} onChange={(e) => set('notes', e.target.value)} /></div>
    </div>
    <div className="note" style={{ marginTop: 12 }}><Icon name="shield" /><div>При сохранении автоматически запускается проверка конфликта интересов по ФИО, ПИН / ИНН и телефону.</div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button><button className="btn" onClick={save}>{t('common.create')}</button></div>
  </Modal>;
}
