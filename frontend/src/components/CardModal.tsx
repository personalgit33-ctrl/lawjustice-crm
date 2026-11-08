'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { del, get, patch, post, upload, fileUrl } from '@/lib/api';
import { useApp } from './AppContext';
import { Icon } from './Icon';
import { Ava, CfTag, ChTag, ErrorState, Loading, Modal } from './ui';
import { pickFiles } from './common';
import { toast, toastErr } from './toast';
import { dt, fromLocalInput, fsize, toLocalInput } from '@/lib/format';
import { t } from '@/i18n';
import type { Attachment, Board, BoardShort, CardDetail, Case, Client, Label } from '@/lib/types';

const LCOLORS = ['#D14343', '#2A47A1', '#0F766E', '#B7791F', '#64748B', '#6D5BD0'];

export function CardModal({ id, labels, onClose, onChanged }: { id: number; labels: Label[]; onClose: () => void; onChanged?: (c: CardDetail | null) => void }) {
  const [c, setC] = useState<CardDetail | null>(null);
  const [err, setErr] = useState<any>(null);
  const [panel, setPanel] = useState<string | null>(null);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [boardLabels, setBoardLabels] = useState<Label[]>(labels);
  const load = () => get<CardDetail>(`cards/${id}/`).then((d) => { setC(d); setErr(null); }).catch(setErr);
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setBoardLabels(labels), [labels]);
  const apply = (d: CardDetail) => { setC(d); onChanged && onChanged(d); };
  const save = async (body: Partial<CardDetail> | Record<string, unknown>) => { try { apply(await patch<CardDetail>(`cards/${id}/`, body)); } catch (e) { toastErr(e); } };
  const act = async (path: string, msg: string, body: any = {}) => { try { const d = await post<CardDetail>(`cards/${id}/${path}/`, body); apply(d); toast(msg); return d; } catch (e) { toastErr(e); } };

  if (err) return <Modal onClose={onClose}><ErrorState error={err} retry={load} /></Modal>;
  if (!c) return <Modal onClose={onClose}><Loading /></Modal>;

  return <Modal onClose={onClose}>
    <div className="muted small">{c.board_name} › {c.list_name}{c.is_archived && ' · в архиве'}</div>
    <TitleEdit value={c.title} onSave={(v) => save({ title: v })} />
    <div className="mgrid"><div>
      <div className="row wrap" style={{ gap: 22, marginBottom: 14, alignItems: 'flex-start' }}>
        <div><div className="lbl">Участники</div><div className="row">{c.members.length ? c.members.map((m) => <MemberAva key={m} id={m} />) : <span className="muted">—</span>}</div></div>
        <div><div className="lbl">Метки</div><div className="labels" style={{ marginTop: 6 }}>{c.labels.length ? c.labels.map((l) => { const lb = boardLabels.find((x) => x.id === l); return lb ? <i key={l} title={lb.name} style={{ background: lb.color, width: 36, height: 18, borderRadius: 3 }} /> : null; }) : <span className="muted">—</span>}</div></div>
        <div><div className="lbl">Срок</div><span className={`due ${c.due_state || ''}`}>{c.due_label || '—'}</span></div>
        <div><div className="lbl">Приоритет</div>{t('prio.' + c.priority)}</div>
        {c.client && <div><div className="lbl">Клиент</div><Link className="lnk" href={`/clients/${c.client}`}>{c.client_name}</Link> <ChTag c={c.source} /></div>}
        {c.case && <div><div className="lbl">Дело</div><Link className="lnk" href={`/cases/${c.case}`}>№ {c.case_number}</Link></div>}
        {c.opponent && <div><div className="lbl">Противная сторона</div>{c.opponent}</div>}
      </div>
      {(c.conflict_status !== 'none' || c.is_confidential) && <div style={{ marginBottom: 12 }} className="row wrap">{c.conflict_status !== 'none' && <CfTag s={c.conflict_status} />}{c.is_confidential && <span className="tag"><Icon name="lock" />Конфиденциально · ассистент отключён</span>}</div>}
      {c.conflict_status === 'hit' && <div className="note r" style={{ marginBottom: 12 }}><Icon name="alert" /><div>Найдено совпадение при проверке конфликта интересов. Перевод в итоговые колонки заблокирован до решения руководителя. <Link className="lnk" href="/conflicts">Открыть проверку</Link></div></div>}
      {c.summary && !c.is_confidential && <div className="sum"><b>Резюме обращения</b><div style={{ marginTop: 4 }}>{c.summary}</div></div>}

      {panel && <SidePanel kind={panel} c={c} boardLabels={boardLabels} setBoardLabels={setBoardLabels} save={save} apply={apply} reload={load} onClose={() => setPanel(null)} />}

      <h3>Описание</h3><Description value={c.description} onSave={(v) => save({ description: v })} />

      <Checklists c={c} reload={load} />

      <h3 style={{ marginTop: 16 }}>Вложения</h3>
      <Attachments c={c} reload={load} onPreview={setPreview} onCover={(a) => act('cover', 'Обложка установлена', { attachment: a.id })} />

      <h3 style={{ marginTop: 16 }}>Комментарии и история</h3>
      <CommentBox cardId={c.id} onDone={load} />
      {c.comments.map((cm) => <div key={'c' + cm.id} className="cmt"><div className="row small"><b style={{ fontWeight: 600 }}>{cm.is_ai ? t('common.assistant') : cm.author_name}</b><span className="muted">{dt(cm.created_at)}</span></div><div style={{ whiteSpace: 'pre-wrap' }}>{highlight(cm.text)}</div>
        {cm.attachments.map((a) => <a key={a.id} className="lnk small" href={fileUrl(a.url)} target="_blank" rel="noreferrer"><Icon name="clip" size={12} /> {a.name}</a>)}</div>)}
      <div className="hist" style={{ marginTop: 10 }}>{c.history.map((h) => <p key={h.id}><b>{h.is_ai ? t('common.assistant') : h.actor_name}</b> {h.text} <span className="muted">· {dt(h.created_at)}</span></p>)}</div>
    </div>
    <div className="sa"><div className="lbl">Добавить</div>
      {([['user', 'Участники', 'members'], ['tagi', 'Метки', 'labels'], ['clock', 'Срок и приоритет', 'due'], ['users', 'Клиент / дело', 'client']] as const).map(([ic, l, k]) => <button key={k} onClick={() => setPanel(panel === k ? null : k)}><Icon name={ic} />{l}</button>)}
      <button onClick={async () => { const fs = await pickFiles(); for (const f of fs) { try { await upload('attachments/', { file: f, card: c.id }); } catch (e) { toastErr(e); } } load(); }}><Icon name="clip" />Вложение</button>
      <div className="lbl" style={{ marginTop: 12 }}>Действия</div>
      <button onClick={() => setPanel(panel === 'move' ? null : 'move')}><Icon name="arrow" />Переместить</button>
      <button onClick={async () => { const d = await act('copy', 'Карточка скопирована'); if (d) onChanged && onChanged(d); }}><Icon name="copy" />Копировать</button>
      <button onClick={() => act('subscribe', c.subscribed ? 'Подписка отключена' : 'Вы подписаны на карточку')}><Icon name="bell" />{c.subscribed ? 'Отписаться' : 'Подписаться'}</button>
      {c.conversation && <Link href={`/inbox?c=${c.conversation}`}><button><Icon name="inbox" />Открыть чат клиента</button></Link>}
      <CreateCaseBtn c={c} reload={load} />
      {c.is_archived ? <button onClick={() => act('restore', 'Карточка восстановлена')}><Icon name="undo" />Восстановить</button>
        : <button onClick={async () => { await act('archive', 'Карточка в архиве'); }}><Icon name="archive" />Архивировать</button>}
    </div></div>
    {preview && <div className="preview" onClick={() => setPreview(null)}>{preview.is_image ? <img src={fileUrl(preview.url)} alt={preview.name} /> : <iframe src={fileUrl(preview.url)} title={preview.name} />}</div>}
  </Modal>;
}

function highlight(s: string) { return s.split(/(@[\wа-яА-ЯёЁ.]+)/g).map((p, i) => p.startsWith('@') ? <b key={i} style={{ color: 'var(--primary)', fontWeight: 600 }}>{p}</b> : p); }
function MemberAva({ id }: { id: number }) { const { userById } = useApp(); const u = userById(id); return <Ava small={false} initials={u?.initials} name={u?.full_name} />; }

function TitleEdit({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value); const [ed, setEd] = useState(false);
  useEffect(() => setV(value), [value]);
  if (!ed) return <h2 style={{ margin: '4px 0 14px', fontSize: 19, cursor: 'text' }} onClick={() => setEd(true)}>{value}</h2>;
  return <input className="fld" style={{ fontSize: 17, fontWeight: 600, margin: '4px 0 14px' }} autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={() => { setEd(false); if (v.trim() && v !== value) onSave(v.trim()); }} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />;
}
function Description({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value); const [ed, setEd] = useState(false);
  useEffect(() => setV(value), [value]);
  if (!ed) return <div className="fld" style={{ color: 'var(--text-history)', marginBottom: 14, whiteSpace: 'pre-wrap', cursor: 'text', minHeight: 40 }} onClick={() => setEd(true)}>{value || <span className="muted">Добавьте описание…</span>}</div>;
  return <div style={{ marginBottom: 14 }}><textarea className="fld" rows={5} autoFocus value={v} onChange={(e) => setV(e.target.value)} />
    <div className="row" style={{ marginTop: 6 }}><button className="btn sm" onClick={() => { onSave(v); setEd(false); }}>{t('common.save')}</button><button className="btn ghost sm" onClick={() => { setV(value); setEd(false); }}>{t('common.cancel')}</button><span className="muted small">Поддерживаются переносы строк и списки «- пункт»</span></div></div>;
}

function Checklists({ c, reload }: { c: CardDetail; reload: () => void }) {
  const [newItem, setNewItem] = useState<Record<number, string>>({});
  const total = c.checklists.reduce((a, l) => a + l.items.length, 0); const done = c.checklists.reduce((a, l) => a + l.items.filter((i) => i.done).length, 0);
  const run = async (fn: () => Promise<any>) => { try { await fn(); reload(); } catch (e) { toastErr(e); } };
  return <>
    <div className="row" style={{ marginBottom: 6 }}><h3 style={{ margin: 0 }}>Чек-лист <span className="muted" style={{ fontWeight: 400 }}>{done}/{total}</span></h3>
      <button className="btn ghost sm" style={{ marginLeft: 'auto' }} onClick={() => { const n = prompt('Название чек-листа', 'Чек-лист'); n && run(() => post('checklists/', { card: c.id, title: n })); }}><Icon name="plus" />Чек-лист</button></div>
    {total > 0 && <div className="bar" style={{ marginBottom: 6 }}><i style={{ width: `${(done / total) * 100}%`, background: 'var(--success)' }} /></div>}
    {c.checklists.map((cl) => <div key={cl.id} style={{ marginBottom: 10 }}>
      <div className="row small" style={{ fontWeight: 600, marginTop: 6 }}>{cl.title}<button className="btn link small" style={{ marginLeft: 'auto', color: 'var(--text-muted)' }} onClick={() => confirm('Удалить чек-лист?') && run(() => del(`checklists/${cl.id}/`))}>удалить</button></div>
      {cl.items.map((it) => <label key={it.id} className={`chk ${it.done ? 'done' : ''}`}><input type="checkbox" checked={it.done} onChange={() => run(() => patch(`checklist-items/${it.id}/`, { done: !it.done }))} /> <span>{it.text}</span>
        {it.due_at && <span className="muted small">до {dt(it.due_at, false)}</span>}
        <button className="x" onClick={(e) => { e.preventDefault(); run(() => del(`checklist-items/${it.id}/`)); }}><Icon name="x" size={13} /></button></label>)}
      <div className="row" style={{ marginTop: 4 }}><input className="fld" style={{ padding: '5px 8px' }} placeholder="Добавить пункт" value={newItem[cl.id] || ''} onChange={(e) => setNewItem({ ...newItem, [cl.id]: e.target.value })}
        onKeyDown={(e) => { const v = (newItem[cl.id] || '').trim(); if (e.key === 'Enter' && v) { setNewItem({ ...newItem, [cl.id]: '' }); run(() => post('checklist-items/', { checklist: cl.id, text: v })); } }} /></div>
    </div>)}
  </>;
}

function Attachments({ c, reload, onPreview, onCover }: { c: CardDetail; reload: () => void; onPreview: (a: Attachment) => void; onCover: (a: Attachment) => void }) {
  const [over, setOver] = useState(false); const [busy, setBusy] = useState(0);
  const send = async (files: File[]) => {
    setBusy(files.length);
    for (const f of files) { if (f.size > 50 * 1024 * 1024) { toast(`${f.name}: больше 50 МБ`, true); continue; } try { await upload('attachments/', { file: f, card: c.id }); } catch (e) { toastErr(e); } }
    setBusy(0); reload();
  };
  const isPdf = (a: Attachment) => a.mime === 'application/pdf' || a.name.toLowerCase().endsWith('.pdf');
  const ext = (n: string) => (n.split('.').pop() || 'FILE').toUpperCase().slice(0, 4);
  return <>
    {c.attachments.length > 0 && <div className="att">{c.attachments.map((a) => <div key={a.id}>
      <div className="th" onClick={() => (a.is_image || isPdf(a)) ? onPreview(a) : window.open(fileUrl(a.url), '_blank')}
        style={a.is_image ? { backgroundImage: `url(${fileUrl(a.url)})` } : { background: isPdf(a) ? 'var(--danger-bg)' : 'var(--tag-neutral-bg)', color: isPdf(a) ? 'var(--danger)' : 'var(--tag-neutral-text)' }}>{a.is_image ? '' : ext(a.name)}</div>
      <div className="nm" title={a.name}>{a.name}</div><div className="muted" style={{ fontSize: 11 }}>{fsize(a.size)}</div>
      <div className="row" style={{ gap: 6, fontSize: 11, marginTop: 2 }}><a className="lnk" href={fileUrl(a.url)} download={a.name} target="_blank" rel="noreferrer">{t('common.download')}</a>
        {a.is_image && <button className="btn link" style={{ fontSize: 11 }} onClick={() => onCover(a)}>Обложка</button>}
        <button className="btn link" style={{ fontSize: 11, color: 'var(--text-muted)' }} onClick={async () => { if (!confirm('Удалить файл?')) return; try { await del(`attachments/${a.id}/`); reload(); } catch (e) { toastErr(e); } }}>{t('common.delete')}</button></div>
    </div>)}</div>}
    <div className={`drop ${over ? 'over' : ''}`} onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}>
      {busy ? `Загрузка файлов: ${busy}…` : <>Перетащите фото или документы сюда или <span className="lnk" onClick={async () => send(await pickFiles())}>выберите файл</span> · до 50 МБ</>}</div>
  </>;
}

function CommentBox({ cardId, onDone }: { cardId: number; onDone: () => void }) {
  const { users } = useApp();
  const [v, setV] = useState(''); const ref = useRef<HTMLInputElement>(null);
  const m = /@([\wа-яА-ЯёЁ.]*)$/.exec(v);
  const sugg = m ? users.filter((u) => u.role !== 'ai' && (u.username.toLowerCase().startsWith(m[1].toLowerCase()) || u.full_name.toLowerCase().includes(m[1].toLowerCase()))).slice(0, 5) : [];
  const send = async () => { if (!v.trim()) return; try { await post('comments/', { card: cardId, text: v.trim() }); setV(''); onDone(); } catch (e) { toastErr(e); } };
  return <div style={{ position: 'relative', marginBottom: 10 }}>
    <div className="row"><input ref={ref} className="fld" placeholder="Комментарий… @упомянуть сотрудника" value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !sugg.length) send(); }} /><button className="btn sm" onClick={send}><Icon name="send" /></button></div>
    {sugg.length > 0 && <div className="sres" style={{ right: 'auto', width: 260 }}>{sugg.map((u) => <a key={u.id} href="#" onClick={(e) => { e.preventDefault(); setV(v.replace(/@[\wа-яА-ЯёЁ.]*$/, '@' + u.username + ' ')); ref.current?.focus(); }}>{u.full_name} <span className="muted small">@{u.username}</span></a>)}</div>}
  </div>;
}

function CreateCaseBtn({ c, reload }: { c: CardDetail; reload: () => void }) {
  const router = useRouter();
  if (c.case) return null;
  return <button onClick={async () => {
    if (!c.client) { toast('Сначала привяжите клиента к карточке', true); return; }
    try { const cs = await post<Case>('cases/', { title: c.title, client: c.client, responsible: c.members[0] ?? null, parties: c.opponent ? [{ role: 'opponent', name: c.opponent, pin: '', phone: '' }] : [] });
      await patch(`cards/${c.id}/`, { case: cs.id }); toast(`Дело № ${cs.number} создано`); reload(); router.push(`/cases/${cs.id}`);
    } catch (e: any) { toast(e.status === 409 ? (e.message || 'Нельзя создать дело: не решён конфликт интересов') : e.message, true); }
  }}><Icon name="case" />Создать дело</button>;
}

function SidePanel({ kind, c, boardLabels, setBoardLabels, save, apply, reload, onClose }: { kind: string; c: CardDetail; boardLabels: Label[]; setBoardLabels: (l: Label[]) => void; save: (b: any) => Promise<void>; apply: (d: CardDetail) => void; reload: () => void; onClose: () => void }) {
  const { users } = useApp();
  const box = (title: string, body: React.ReactNode) => <div className="card" style={{ marginBottom: 14, background: 'var(--primary-lighter)' }}><div className="row" style={{ marginBottom: 8 }}><b style={{ fontWeight: 600 }}>{title}</b><button className="ib" style={{ marginLeft: 'auto', width: 26, height: 26 }} onClick={onClose}><Icon name="x" /></button></div>{body}</div>;
  if (kind === 'members') return box('Участники', <div className="picker">{users.filter((u) => u.is_active && u.role !== 'ai').map((u) => { const on = c.members.includes(u.id); return <button key={u.id} className={on ? 'on' : ''} onClick={() => save({ members: on ? c.members.filter((x) => x !== u.id) : [...c.members, u.id] })}><Ava initials={u.initials} />{u.full_name}</button>; })}</div>);
  if (kind === 'labels') return box('Метки', <LabelsPanel c={c} boardLabels={boardLabels} setBoardLabels={setBoardLabels} save={save} />);
  if (kind === 'due') return box('Срок и приоритет', <div className="fg">
    <div><div className="lbl">Дата начала</div><input type="datetime-local" className="fld" defaultValue={toLocalInput(c.start_at)} onBlur={(e) => save({ start_at: fromLocalInput(e.target.value) })} /></div>
    <div><div className="lbl">Срок</div><input type="datetime-local" className="fld" defaultValue={toLocalInput(c.due_at)} onBlur={(e) => save({ due_at: fromLocalInput(e.target.value) })} /></div>
    <div><div className="lbl">Приоритет</div><select className="fld" value={c.priority} onChange={(e) => save({ priority: e.target.value })}>{(['low', 'normal', 'high', 'urgent'] as const).map((p) => <option key={p} value={p}>{t('prio.' + p)}</option>)}</select></div>
    <div style={{ alignSelf: 'end' }}><button className="btn ghost sm" onClick={() => save({ due_at: null })}>Снять срок</button></div></div>);
  if (kind === 'client') return box('Клиент и дело', <ClientCasePanel c={c} save={save} />);
  if (kind === 'move') return box('Переместить', <MovePanel c={c} apply={apply} reload={reload} onClose={onClose} />);
  return null;
}

function LabelsPanel({ c, boardLabels, setBoardLabels, save }: { c: CardDetail; boardLabels: Label[]; setBoardLabels: (l: Label[]) => void; save: (b: any) => Promise<void> }) {
  const [name, setName] = useState(''); const [color, setColor] = useState(LCOLORS[0]);
  return <><div className="picker" style={{ marginBottom: 10 }}>{boardLabels.map((l) => { const on = c.labels.includes(l.id); return <button key={l.id} className={on ? 'on' : ''} onClick={() => save({ labels: on ? c.labels.filter((x) => x !== l.id) : [...c.labels, l.id] })}><i style={{ width: 14, height: 8, borderRadius: 2, background: l.color, display: 'inline-block' }} />{l.name || 'Без названия'}</button>; })}</div>
    <div className="row"><input className="fld" placeholder="Новая метка" value={name} onChange={(e) => setName(e.target.value)} />
      {LCOLORS.map((x) => <button key={x} onClick={() => setColor(x)} style={{ width: 20, height: 20, borderRadius: 4, background: x, outline: color === x ? '2px solid var(--text)' : 'none', flex: 'none' }} />)}
      <button className="btn sm" onClick={async () => { if (!name.trim()) return; try { const l = await post<Label>('labels/', { board: c.board, name: name.trim(), color }); setBoardLabels([...boardLabels, l]); setName(''); await save({ labels: [...c.labels, l.id] }); } catch (e) { toastErr(e); } }}>{t('common.add')}</button></div></>;
}

function ClientCasePanel({ c, save }: { c: CardDetail; save: (b: any) => Promise<void> }) {
  const [q, setQ] = useState(''); const [clients, setClients] = useState<Client[]>([]); const [cases, setCases] = useState<Case[]>([]);
  useEffect(() => { const h = setTimeout(() => get<Client[]>(`clients/?search=${encodeURIComponent(q)}`).then((x) => setClients(x.slice(0, 8))).catch(() => {}), 250); return () => clearTimeout(h); }, [q]);
  useEffect(() => { if (c.client) get<Case[]>(`cases/?search=`).then((x) => setCases(x.filter((y) => y.client === c.client))).catch(() => {}); }, [c.client]);
  return <div className="fg">
    <div className="full"><div className="lbl">Клиент {c.client_name && <>— сейчас: <b>{c.client_name}</b></>}</div><input className="fld" placeholder="Поиск клиента по имени или телефону" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="picker" style={{ marginTop: 6 }}>{clients.map((x) => <button key={x.id} className={c.client === x.id ? 'on' : ''} onClick={() => save({ client: x.id })}>{x.name}</button>)}{c.client && <button onClick={() => save({ client: null })}>Отвязать</button>}</div></div>
    {c.client ? <div className="full"><div className="lbl">Дело клиента</div><select className="fld" value={c.case ?? ''} onChange={(e) => save({ case: e.target.value ? Number(e.target.value) : null })}><option value="">—</option>{cases.map((x) => <option key={x.id} value={x.id}>№ {x.number} · {x.title}</option>)}</select></div> : null}
  </div>;
}

function MovePanel({ c, apply, reload, onClose }: { c: CardDetail; apply: (d: CardDetail) => void; reload: () => void; onClose: () => void }) {
  const [boards, setBoards] = useState<BoardShort[]>([]); const [bid, setBid] = useState(c.board); const [b, setB] = useState<Board | null>(null); const [lid, setLid] = useState<number>(c.list);
  useEffect(() => { get<BoardShort[]>('boards/').then(setBoards).catch(() => {}); }, []);
  useEffect(() => { get<Board>(`boards/${bid}/`).then((x) => { setB(x); if (!x.lists.some((l) => l.id === lid)) setLid(x.lists[0]?.id); }).catch(() => {}); }, [bid]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="fg">
    <div><div className="lbl">Доска</div><select className="fld" value={bid} onChange={(e) => setBid(Number(e.target.value))}>{boards.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></div>
    <div><div className="lbl">Колонка</div><select className="fld" value={lid} onChange={(e) => setLid(Number(e.target.value))}>{b?.lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></div>
    <div className="full"><button className="btn sm" onClick={async () => { try { const d = await post<CardDetail>(`cards/${c.id}/move/`, { list: lid, position: b?.lists.find((l) => l.id === lid)?.cards.length ?? 0 }); apply(d); toast(`Карточка перемещена в «${d.list_name}»`); onClose(); } catch (e: any) { toast(e.message, true); reload(); } }}>Переместить</button></div>
  </div>;
}
