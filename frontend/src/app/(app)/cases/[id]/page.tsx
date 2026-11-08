'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { del, get, patch, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { CfTag, DueTag, Empty, View, useLoad } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { NewDeadline } from '@/components/NewDeadline';
import { toast, toastErr } from '@/components/toast';
import { dt } from '@/lib/format';
import { t } from '@/i18n';
import type { Case, Deadline, Party, TimelineItem } from '@/lib/types';

const ROLE: Record<Party['role'], string> = { client: 'Клиент', opponent: 'Противная сторона', third: 'Третье лицо' };

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const { dict, users } = useApp();
  const s = useLoad(() => get<Case>(`cases/${id}/`), [id]);
  const tl = useLoad(() => get<TimelineItem[]>(`cases/${id}/timeline/`), [id]);
  const dls = useLoad(() => get<Deadline[]>(`deadlines/?state=all&case=${id}`), [id]);
  const [addDl, setAddDl] = useState(false);
  const [np, setNp] = useState<Pick<Party, 'role' | 'name' | 'pin' | 'phone'>>({ role: 'opponent', name: '', pin: '', phone: '' });
  const upd = async (body: Partial<Case>) => {
    try { s.setData(await patch<Case>(`cases/${id}/`, body)); toast('Сохранено'); tl.reload(true); }
    catch (e: any) { toast(e.status === 409 ? (e.message || 'Нельзя изменить статус: не принято решение по конфликту интересов') : e.message, true); s.reload(true); }
  };
  const addParty = async () => { if (!np.name.trim()) return; try { await post('parties/', { ...np, case: Number(id) }); setNp({ role: 'opponent', name: '', pin: '', phone: '' }); s.reload(true); toast('Сторона добавлена · проверка конфликта выполнена'); } catch (e) { toastErr(e); } };
  return <View s={s}>{(c) => c.restricted ? <div className="card"><div className="row"><Link href="/cases" className="btn ghost sm"><Icon name="left" />Дела</Link><b>№ {c.number}</b><span className="tag"><Icon name="lock" />Конфиденциально</span></div>
    <div className="note" style={{ marginTop: 14 }}><Icon name="lock" /><div>Дело конфиденциальное. Материалы доступны только назначенным участникам и руководителю.</div></div></div> : <>
    <div className="row wrap" style={{ marginBottom: 14 }}><Link href="/cases" className="btn ghost sm"><Icon name="left" />Дела</Link>
      <h2 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>№ {c.number} · {c.title}</h2>
      {c.is_confidential && <span className="tag"><Icon name="lock" />Конфиденциально · ассистент отключён</span>}<CfTag s={c.conflict_status} />{c.stale && <span className="tag a">Без движения дольше 7 дней</span>}</div>
    {c.conflict_status === 'hit' && <div className="note r" style={{ marginBottom: 14 }}><Icon name="alert" /><div>Найдено совпадение при проверке конфликта интересов. Перевод в «В работе» заблокирован до решения руководителя. <Link className="lnk" href="/conflicts">Открыть проверку</Link></div></div>}
    <div className="grid gside">
      <div>
        <div className="card"><div className="fg">
          <div><div className="lbl">Статус</div><select className="fld" value={c.status} onChange={(e) => upd({ status: e.target.value })}>{dict.case_status.map((x) => <option key={x.id} value={x.code}>{x.name}</option>)}</select></div>
          <div><div className="lbl">Категория</div><select className="fld" value={c.category} onChange={(e) => upd({ category: e.target.value })}>{dict.case_category.map((x) => <option key={x.id}>{x.name}</option>)}{!dict.case_category.some((x) => x.name === c.category) && <option>{c.category}</option>}</select></div>
          <div><div className="lbl">Клиент</div><Link className="lnk" href={`/clients/${c.client}`}>{c.client_name}</Link></div>
          <div><div className="lbl">Ответственный юрист</div><UserSelect value={c.responsible} onChange={(x) => upd({ responsible: x })} /></div>
          <div><div className="lbl">Суд / инстанция</div><input className="fld" defaultValue={c.court} onBlur={(e) => e.target.value !== c.court && upd({ court: e.target.value })} /></div>
          <div><div className="lbl">Гонорар</div><div>{c.fee != null ? `${c.fee.toLocaleString('ru-RU')} сом` : '—'} <Link className="lnk small" href="/finance">договор и оплаты</Link></div></div>
          <div className="full"><div className="lbl">Участники дела (доступ)</div><div className="picker">{users.filter((u) => u.is_active && u.role !== 'ai').map((u) => <button key={u.id} className={c.members.includes(u.id) ? 'on' : ''} onClick={() => upd({ members: c.members.includes(u.id) ? c.members.filter((x) => x !== u.id) : [...c.members, u.id] })}>{u.full_name}</button>)}</div></div>
          <label className="full chk"><input type="checkbox" checked={c.is_confidential} onChange={(e) => upd({ is_confidential: e.target.checked })} /> Конфиденциальное дело</label>
          {c.is_archived ? <div className="full"><button className="btn ghost sm" onClick={() => upd({ is_archived: false })}><Icon name="undo" />Вернуть из архива</button></div> : null}
        </div></div>
        <div className="card np" style={{ marginTop: 14 }}><div className="ch" style={{ padding: '14px 16px 0' }}><h3>Сроки и события</h3><button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => setAddDl(true)}><Icon name="plus" />Срок</button></div>
          <View s={dls}>{(list) => list.length === 0 ? <Empty text="Сроков нет" /> : <table><tbody>{list.map((d) => <tr key={d.id}><td style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>{d.due_label}</td><td>{d.title}<div className="muted small">{d.type_label}{d.court && ` · ${d.court}`}</div></td><td><DueTag s={d.state} /></td></tr>)}</tbody></table>}</View></div>
        <div className="card" style={{ marginTop: 14 }}><h3>Хронология</h3><View s={tl}>{(items) => items.length === 0 ? <Empty /> : <div className="tl">{items.map((i) => <div key={i.id}><div className="muted small">{dt(i.created_at)} · {i.is_ai ? <span className="tag b">{t('common.assistant')}</span> : i.actor}</div><div>{i.link ? <Link className="lnk" href={i.link}>{i.text}</Link> : i.text}</div></div>)}</div>}</View></div>
      </div>
      <div><div className="card"><h3>Стороны дела</h3>
        {c.parties.length === 0 ? <div className="muted small">Стороны не указаны</div> : c.parties.map((p) => <div key={p.id} className="set"><div>{p.name}<small>{ROLE[p.role]}{p.pin && ` · ${p.pin}`}{p.phone && ` · ${p.phone}`}</small></div>
          {p.role !== 'client' && <button className="ib" onClick={async () => { try { await del(`parties/${p.id}/`); s.reload(true); } catch (e) { toastErr(e); } }}><Icon name="x" /></button>}</div>)}
        <div style={{ marginTop: 10 }}><select className="fld" value={np.role} onChange={(e) => setNp({ ...np, role: e.target.value as any })} style={{ marginBottom: 6 }}><option value="opponent">Противная сторона</option><option value="third">Третье лицо</option></select>
          <input className="fld" placeholder="ФИО / наименование" value={np.name} onChange={(e) => setNp({ ...np, name: e.target.value })} style={{ marginBottom: 6 }} />
          <div className="row" style={{ marginBottom: 6 }}><input className="fld" placeholder="ПИН / ИНН" value={np.pin} onChange={(e) => setNp({ ...np, pin: e.target.value })} /><input className="fld" placeholder="Телефон" value={np.phone} onChange={(e) => setNp({ ...np, phone: e.target.value })} /></div>
          <button className="btn ghost sm" onClick={addParty}><Icon name="plus" />Добавить сторону</button></div></div>
        <div className="card" style={{ marginTop: 14 }}><h3>Сведения</h3><div className="kv"><span>Создано</span><div>{dt(c.created_at)}</div><span>Изменено</span><div>{dt(c.updated_at)}</div><span>Ближайший срок</span><div>{c.nearest_deadline ? dt(c.nearest_deadline) : '—'}</div></div></div>
      </div>
    </div>
    {addDl && <NewDeadline caseId={c.id} onClose={() => setAddDl(false)} onDone={() => { setAddDl(false); dls.reload(true); s.reload(true); }} />}
  </>}</View>;
}
