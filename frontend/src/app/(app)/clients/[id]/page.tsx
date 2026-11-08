'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { get, patch, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { CfTag, ChTag, Empty, Modal, View, useLoad, DueTag } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { dt, dur, fsize } from '@/lib/format';
import { isManager } from '@/lib/access';
import { t } from '@/i18n';
import type { Attachment, Call, CardSummary, Case, Client, Conversation, TimelineItem } from '@/lib/types';

type Related = { cases: Case[]; cards: (CardSummary & { board_name?: string })[]; conversations: Conversation[]; calls: Call[]; files: Attachment[] };

export default function ClientPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter(); const { user } = useApp();
  const s = useLoad(() => get<Client>(`clients/${id}/`), [id]);
  const tl = useLoad(() => get<TimelineItem[]>(`clients/${id}/timeline/`), [id]);
  const rel = useLoad(() => get<Related>(`clients/${id}/related/`), [id]);
  const [tab, setTab] = useState<'timeline' | 'cases' | 'cards' | 'chats' | 'calls' | 'files'>('timeline');
  const [edit, setEdit] = useState(false); const [merge, setMerge] = useState(false);
  const call = async (c: Client) => { try { await post('calls/originate/', { phone: c.phone, client: c.id }); toast(`Звонок ${c.phone} через IP-телефонию`); } catch (e) { toastErr(e); } };
  const consent = async (c: Client, status: 'given' | 'revoked') => {
    const text = status === 'given' ? 'Согласие на обработку персональных данных получено' : 'Клиент отозвал согласие на обработку персональных данных';
    try { s.setData(await post<Client>(`clients/${c.id}/consent/`, { status, channel: 'вручную', text })); toast(status === 'given' ? 'Согласие зафиксировано' : 'Отзыв согласия зафиксирован'); tl.reload(true); } catch (e) { toastErr(e); }
  };
  return <View s={s}>{(c) => <>
    <div className="row wrap" style={{ marginBottom: 14 }}><Link href="/clients" className="btn ghost sm"><Icon name="left" />Клиенты</Link><h2 style={{ margin: 0, fontSize: 19, fontWeight: 600 }}>{c.name}</h2><span className="tag">{c.kind === 'company' ? 'Юрлицо' : 'Физлицо'}</span><CfTag s={c.conflict_status} />
      <div style={{ marginLeft: 'auto' }} className="row wrap">{c.phone && <button className="btn sm" onClick={() => call(c)}><Icon name="phone" />Позвонить</button>}<button className="btn ghost sm" onClick={() => setEdit(true)}>{t('common.edit')}</button>{isManager(user.role) && <button className="btn ghost sm" onClick={() => setMerge(true)}>Слить дубль</button>}</div></div>
    <div className="grid gcl">
      <div><div className="card"><h3>Данные клиента</h3><div className="kv">
        <span>Телефон</span><div>{c.phone || '—'}</div><span>Email</span><div>{c.email || '—'}</div><span>{c.kind === 'company' ? 'ИНН' : 'ПИН'}</span><div>{c.pin || '—'}</div><span>Город</span><div>{c.city || '—'}</div>
        <span>Источник</span><div><ChTag c={c.source} /> {c.campaign}</div><span>Ответств.</span><div>{c.responsible_name || '—'}</div><span>Создан</span><div>{dt(c.created_at)}</div><span>Контакт</span><div>{c.last_contact_label || '—'}</div></div>
        {c.notes && <div className="sum"><b>Заметки</b><div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{c.notes}</div></div>}</div>
        <div className="card" style={{ marginTop: 14 }}><h3>Согласие на обработку ПД</h3>
          {c.consent_status === 'given' ? <div className="note"><Icon name="ok" /><div>Получено {dt(c.consent_at, false)} · {c.consent_channel}</div></div> : c.consent_status === 'revoked' ? <div className="note r"><Icon name="alert" /><div>Отозвано {dt(c.consent_at, false)}. Обработка данных ограничена.</div></div> : <div className="note w"><Icon name="alert" /><div>Согласие не получено</div></div>}
          <div className="row" style={{ marginTop: 10 }}>{c.consent_status !== 'given' && <button className="btn ghost sm" onClick={() => consent(c, 'given')}>Зафиксировать согласие</button>}{c.consent_status === 'given' && <button className="btn ghost sm" onClick={() => consent(c, 'revoked')}>Отзыв согласия</button>}</div></div></div>
      <div className="card">
        <div className="tabs">{([['timeline', 'Хронология'], ['cases', `Дела ${rel.data?.cases.length ?? ''}`], ['cards', `Карточки ${rel.data?.cards.length ?? ''}`], ['chats', `Диалоги ${rel.data?.conversations.length ?? ''}`], ['calls', `Звонки ${rel.data?.calls.length ?? ''}`], ['files', `Документы ${rel.data?.files.length ?? ''}`]] as const).map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'timeline' ? <View s={tl}>{(items) => items.length === 0 ? <Empty /> : <div className="tl">{items.map((i) => <div key={i.id}><div className="muted small">{dt(i.created_at)} · {i.is_ai ? <span className="tag b">{t('common.assistant')}</span> : i.actor}</div><div>{i.link ? <Link className="lnk" href={i.link}>{i.text}</Link> : i.text}</div></div>)}</div>}</View>
          : <View s={rel}>{(r) => {
            if (tab === 'cases') return r.cases.length ? <table><tbody>{r.cases.map((x) => <tr key={x.id} className="click" onClick={() => router.push(`/cases/${x.id}`)}><td className="muted">№ {x.number}</td><td><b style={{ fontWeight: 500 }}>{x.title}</b></td><td><span className="tag b">{x.status_label}</span></td><td>{x.responsible_name}</td><td><DueTag s={x.nearest_deadline_state} /></td></tr>)}</tbody></table> : <Empty text="Дел нет" />;
            if (tab === 'cards') return r.cards.length ? <table><tbody>{r.cards.map((x) => <tr key={x.id} className="click" onClick={() => router.push(`/boards?card=${x.id}`)}><td><b style={{ fontWeight: 500 }}>{x.title}</b></td><td className="muted">{x.board_name}</td><td>{x.due_label}</td></tr>)}</tbody></table> : <Empty text="Карточек нет" />;
            if (tab === 'chats') return r.conversations.length ? <table><tbody>{r.conversations.map((x) => <tr key={x.id} className="click" onClick={() => router.push(`/inbox?c=${x.id}`)}><td><ChTag c={x.channel} /></td><td>{x.last_message}</td><td className="muted small">{x.last_label}</td></tr>)}</tbody></table> : <Empty text="Диалогов нет" />;
            if (tab === 'calls') return r.calls.length ? <table><tbody>{r.calls.map((x) => <tr key={x.id} className="click" onClick={() => router.push('/calls')}><td><Icon name={x.direction === 'in' ? 'in' : 'out'} /></td><td>{x.started_label}</td><td><span className={`tag ${x.status === 'missed' ? 'r' : 'g'}`}>{t('call.' + x.status)}</span></td><td>{dur(x.duration)}</td><td className="small muted">{x.summary}</td></tr>)}</tbody></table> : <Empty text="Звонков нет" />;
            return r.files.length ? <table><tbody>{r.files.map((x) => <tr key={x.id}><td><a className="lnk" href={x.url} target="_blank" rel="noreferrer">{x.name}</a></td><td className="muted">{fsize(x.size)}</td><td className="muted small">{dt(x.created_at)} · {x.uploaded_by_name}</td></tr>)}</tbody></table> : <Empty text="Документов нет" />;
          }}</View>}
      </div>
    </div>
    {edit && <EditClient c={c} onClose={() => setEdit(false)} onDone={(n) => { s.setData(n); setEdit(false); toast('Сохранено'); }} />}
    {merge && <MergeModal c={c} onClose={() => setMerge(false)} onDone={(n) => { setMerge(false); toast('Дубли объединены'); router.replace(`/clients/${n.id}`); s.reload(); rel.reload(); tl.reload(); }} />}
  </>}</View>;
}

function EditClient({ c, onClose, onDone }: { c: Client; onClose: () => void; onDone: (c: Client) => void }) {
  const [v, setV] = useState({ name: c.name, phone: c.phone, email: c.email, pin: c.pin, city: c.city, notes: c.notes, responsible: c.responsible, kind: c.kind });
  const set = (k: string, x: any) => setV({ ...v, [k]: x });
  return <Modal small onClose={onClose}><h2>Редактировать клиента</h2><div className="fg">
    <div className="full"><div className="lbl">Имя / наименование</div><input className="fld" value={v.name} onChange={(e) => set('name', e.target.value)} /></div>
    <div><div className="lbl">Телефон</div><input className="fld" value={v.phone} onChange={(e) => set('phone', e.target.value)} /></div>
    <div><div className="lbl">Email</div><input className="fld" value={v.email} onChange={(e) => set('email', e.target.value)} /></div>
    <div><div className="lbl">ПИН / ИНН</div><input className="fld" value={v.pin} onChange={(e) => set('pin', e.target.value)} /></div>
    <div><div className="lbl">Город</div><input className="fld" value={v.city} onChange={(e) => set('city', e.target.value)} /></div>
    <div className="full"><div className="lbl">Ответственный</div><UserSelect value={v.responsible} onChange={(x) => set('responsible', x)} /></div>
    <div className="full"><div className="lbl">Заметки</div><textarea className="fld" rows={3} value={v.notes} onChange={(e) => set('notes', e.target.value)} /></div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button><button className="btn" onClick={async () => { try { onDone(await patch<Client>(`clients/${c.id}/`, v)); } catch (e) { toastErr(e); } }}>{t('common.save')}</button></div>
  </Modal>;
}

function MergeModal({ c, onClose, onDone }: { c: Client; onClose: () => void; onDone: (c: Client) => void }) {
  const [q, setQ] = useState(c.phone || c.name); const [res, setRes] = useState<Client[] | null>(null); const [dup, setDup] = useState<number | null>(null);
  const find = async () => { try { setRes((await get<Client[]>(`clients/?search=${encodeURIComponent(q)}`)).filter((x) => x.id !== c.id)); } catch (e) { toastErr(e); } };
  return <Modal small onClose={onClose}><h2>Слияние дублей</h2>
    <div className="muted small" style={{ marginBottom: 8 }}>Дела, диалоги, звонки и файлы дубля перейдут в карточку «{c.name}». Дубль будет удалён.</div>
    <div className="cmd"><input className="fld" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && find()} /><button className="btn" onClick={find}><Icon name="search" /></button></div>
    {res && (res.length === 0 ? <Empty text="Дублей не найдено" /> : <div className="picker" style={{ marginTop: 10 }}>{res.map((x) => <button key={x.id} className={dup === x.id ? 'on' : ''} onClick={() => setDup(x.id)}>{x.name} · {x.phone}</button>)}</div>)}
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" disabled={!dup} onClick={async () => { try { onDone(await post<Client>('clients/merge/', { primary: c.id, duplicate: dup })); } catch (e) { toastErr(e); } }}>Объединить</button></div>
  </Modal>;
}
