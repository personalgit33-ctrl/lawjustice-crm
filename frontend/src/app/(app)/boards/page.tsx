'use client';
import { Fragment, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { get, patch, post, upload, del, fileUrl } from '@/lib/api';
import { useEvents } from '@/lib/ws';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { CardModal } from '@/components/CardModal';
import { Ava, ChTag, Empty, ErrorState, Loading, Modal, Seg, useLoad } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { dt, ymd } from '@/lib/format';
import { isManager } from '@/lib/access';
import { t } from '@/i18n';
import type { Automation, Board, BoardList, BoardShort, CardDetail, CardSummary } from '@/lib/types';

type ViewMode = 'board' | 'list' | 'cal';
type Filters = { member: string; label: string; due: string; client: string };
const noF: Filters = { member: '', label: '', due: '', client: '' };

export default function BoardsPage() { return <Suspense fallback={<Loading />}><Boards /></Suspense>; }

function Boards() {
  const sp = useSearchParams(); const router = useRouter();
  const { user } = useApp();
  const boards = useLoad(() => get<BoardShort[]>('boards/'));
  const [bid, setBid] = useState<number | null>(sp.get('board') ? Number(sp.get('board')) : null);
  const [openCard, setOpenCard] = useState<number | null>(sp.get('card') ? Number(sp.get('card')) : null);
  const [view, setView] = useState<ViewMode>('board');
  const [f, setF] = useState<Filters>(noF);
  const [showF, setShowF] = useState(false);
  const [modal, setModal] = useState<'new' | 'import' | 'settings' | null>(null);

  useEffect(() => {
    if (bid == null && boards.data?.length) { const fav = boards.data.find((b) => b.is_favorite && !b.is_archived) || boards.data.find((b) => !b.is_archived); fav && setBid(fav.id); }
  }, [boards.data, bid]);
  // карточка по ссылке без указания доски
  useEffect(() => { const c = sp.get('card'); if (c && !sp.get('board')) get<CardDetail>(`cards/${c}/`).then((d) => setBid(d.board)).catch(() => {}); }, [sp]);

  const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const board = useLoad(() => bid ? get<Board>(`boards/${bid}/${q ? '?' + q : ''}`) : Promise.resolve(null as any), [bid, q]);
  useEvents((e) => {
    if (['card.moved', 'card.updated', 'card.created', 'board.updated'].includes(e.type)) {
      const b = e.payload?.board ?? e.payload?.board_id;
      if (!b || b === bid) board.reload(true);
      if (e.type === 'board.updated') boards.reload(true);
    }
  }, [bid]);

  const selectBoard = (id: number) => { setBid(id); setF(noF); router.replace(`/boards?board=${id}`); };
  const b = board.data as Board | null;

  return <>
    <div className="bhead">
      {boards.data && <Seg<string> value={String(bid ?? '')} onChange={(v) => selectBoard(Number(v))} options={boards.data.filter((x) => !x.is_archived).map((x) => [String(x.id), <span key={x.id} className="row" style={{ gap: 5 }}>{x.is_favorite && <Icon name="star" size={12} />}{x.name}</span>])} />}
      <button className="btn ghost sm" onClick={() => setModal('new')}><Icon name="plus" />Доска</button>
      <div style={{ marginLeft: 'auto' }} className="row wrap">
        <CardSearch onOpen={(id, board) => { setBid(board); setOpenCard(id); }} />
        <Seg<ViewMode> value={view} onChange={setView} options={[['board', 'Доска'], ['list', 'Список'], ['cal', 'Календарь']]} />
        <button className={`btn ghost sm`} onClick={() => setShowF(!showF)} style={Object.values(f).some(Boolean) ? { borderColor: 'var(--primary)', color: 'var(--primary)', background: 'var(--primary-light)' } : undefined}><Icon name="filter" />{t('common.filter')}</button>
        {b && <button className="btn ghost sm" onClick={() => setModal('settings')}><Icon name="set" />Настройки доски</button>}
        {isManager(user.role) && <button className="btn ghost sm" onClick={() => setModal('import')}><Icon name="dl" />Импорт из Trello</button>}
        {isManager(user.role) && <button className="btn sm" onClick={() => router.push('/assistant')}><Icon name="term" />Создать через ассистента</button>}
      </div>
    </div>
    {showF && b && <FilterBar f={f} setF={setF} board={b} />}
    {boards.error ? <ErrorState error={boards.error} retry={boards.reload} /> : boards.data && !boards.data.length ? <Empty text="Досок пока нет — создайте первую или импортируйте из Trello" /> :
      board.loading && !b ? <Loading /> : board.error && !b ? <ErrorState error={board.error} retry={board.reload} /> : !b ? null :
      view === 'board' ? <Kanban b={b} setB={(nb) => board.setData(nb)} reload={() => board.reload(true)} onOpen={setOpenCard} /> :
      view === 'list' ? <ListView b={b} onOpen={setOpenCard} /> : <CalView b={b} onOpen={setOpenCard} />}
    {openCard != null && <CardModal id={openCard} labels={b?.labels || []} onClose={() => { setOpenCard(null); router.replace(bid ? `/boards?board=${bid}` : '/boards'); board.reload(true); }} onChanged={() => board.reload(true)} />}
    {modal === 'new' && <NewBoard onClose={() => setModal(null)} onDone={(nb) => { setModal(null); boards.reload(true); selectBoard(nb.id); }} />}
    {modal === 'import' && <TrelloImport onClose={() => setModal(null)} onDone={() => { boards.reload(true); board.reload(true); }} />}
    {modal === 'settings' && b && <BoardSettings b={b} onClose={() => setModal(null)} onChanged={(archived) => { boards.reload(true); board.reload(true); if (archived) { setBid(null); setModal(null); } }} />}
  </>;
}

function FilterBar({ f, setF, board }: { f: Filters; setF: (f: Filters) => void; board: Board }) {
  return <div className="card row wrap" style={{ marginBottom: 12, padding: 10 }}>
    <div style={{ width: 200 }}><UserSelect value={f.member ? Number(f.member) : null} onChange={(v) => setF({ ...f, member: v ? String(v) : '' })} empty="Любой участник" /></div>
    <select className="fld" style={{ width: 180 }} value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })}><option value="">Любая метка</option>{board.labels.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
    <select className="fld" style={{ width: 170 }} value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })}><option value="">Любой срок</option><option value="late">Просрочено</option><option value="week">Ближайшая неделя</option></select>
    <input className="fld" style={{ width: 200 }} placeholder="Клиент" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} />
    <button className="btn ghost sm" onClick={() => setF(noF)}>Сбросить</button>
  </div>;
}

function CardSearch({ onOpen }: { onOpen: (id: number, board: number) => void }) {
  const [q, setQ] = useState(''); const [res, setRes] = useState<any[] | null>(null);
  useEffect(() => { if (q.trim().length < 2) { setRes(null); return; } const h = setTimeout(() => get<any[]>(`cards/search/?q=${encodeURIComponent(q)}`).then(setRes).catch(() => setRes([])), 250); return () => clearTimeout(h); }, [q]);
  return <div style={{ position: 'relative' }}><input className="fld" style={{ width: 220, padding: '5px 9px' }} placeholder="Поиск по карточкам всех досок" value={q} onChange={(e) => setQ(e.target.value)} />
    {res && <div className="sres" style={{ width: 320, left: 'auto', right: 0 }}>{res.length === 0 ? <div className="state" style={{ padding: 14 }}>{t('search.nothing')}</div> : res.map((c) => <a key={c.id} href="#" onClick={(e) => { e.preventDefault(); setRes(null); setQ(''); onOpen(c.id, c.board ?? c.board_id); }}><div style={{ fontWeight: 500 }}>{c.title}</div><div className="muted small">{c.board_name} › {c.list_name}</div></a>)}</div>}
  </div>;
}

function CardTile({ c, labels, onOpen, onDragStart, onDragEnd, dragging }: { c: CardSummary; labels: Board['labels']; onOpen: () => void; onDragStart?: (e: React.DragEvent) => void; onDragEnd?: () => void; dragging?: boolean }) {
  const { userById } = useApp();
  return <div className={`kc ${dragging ? 'drag' : ''}`} draggable={!!onDragStart} onDragStart={onDragStart} onDragEnd={onDragEnd} onClick={onOpen}>
    {c.cover_url && <div className="cover" style={{ backgroundImage: `url(${fileUrl(c.cover_url)})` }} />}
    {c.labels.length > 0 && <div className="labels">{c.labels.map((l) => { const lb = labels.find((x) => x.id === l); return lb ? <i key={l} title={lb.name} style={{ background: lb.color }} /> : null; })}</div>}
    <span className="t">{c.title}</span>
    <div className="meta">
      {c.due_label && <span className={`due ${c.due_state || ''}`}><Icon name="clock" />{c.due_label}</span>}
      {c.checklist[1] > 0 && <span><Icon name="chk" />{c.checklist[0]}/{c.checklist[1]}</span>}
      {c.attachments_count > 0 && <span><Icon name="clip" />{c.attachments_count}</span>}
      {c.comments_count > 0 && <span><Icon name="msg" />{c.comments_count}</span>}
      {c.is_confidential && <span title="Конфиденциально"><Icon name="lock" /></span>}
      {c.conflict_status === 'hit' && <span className="tag r" style={{ fontSize: 10.5 }}>Конфликт</span>}
      {c.priority === 'urgent' && <span className="tag r" style={{ fontSize: 10.5 }}>Срочно</span>}
      {c.ai_created && <span className="tag b" style={{ fontSize: 10.5 }}>{t('common.assistant')}</span>}
      <ChTag c={c.source} />
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>{c.members.map((m) => { const u = userById(m); return <Ava key={m} initials={u?.initials} name={u?.full_name} />; })}</span>
    </div>
  </div>;
}

function Kanban({ b, setB, reload, onOpen }: { b: Board; setB: (b: Board) => void; reload: () => void; onOpen: (id: number) => void }) {
  const drag = useRef<{ card: number; from: number } | null>(null);
  const listDrag = useRef<number | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [adding, setAdding] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [editList, setEditList] = useState<number | null>(null);

  const moveLocal = (board: Board, cardId: number, toList: number, pos: number): Board => {
    let card: CardSummary | undefined;
    const lists = board.lists.map((l) => ({ ...l, cards: l.cards.filter((c) => { if (c.id === cardId) { card = c; return false; } return true; }) }));
    if (!card) return board;
    const tgt = lists.find((l) => l.id === toList)!; const cc = [...tgt.cards]; cc.splice(Math.min(pos, cc.length), 0, { ...card, list: toList }); tgt.cards = cc;
    return { ...board, lists };
  };
  const drop = async (toList: number, pos: number) => {
    const d = drag.current; drag.current = null; setDragId(null); setOver(null);
    if (!d) return;
    const prev = b; const fromList = b.lists.find((l) => l.id === d.from); const idx = fromList?.cards.findIndex((c) => c.id === d.card) ?? -1;
    if (d.from === toList && (idx === pos || idx + 1 === pos)) return;
    const adj = d.from === toList && idx < pos ? pos - 1 : pos;
    setB(moveLocal(b, d.card, toList, adj));
    try { await post(`cards/${d.card}/move/`, { list: toList, position: adj }); const l = b.lists.find((x) => x.id === toList); if (d.from !== toList) toast(`Карточка перемещена в «${l?.name}»`); reload(); }
    catch (e: any) { setB(prev); toast(e.status === 409 ? (e.message || 'Нельзя перенести: не принято решение по конфликту интересов') : e.message, true); }
  };
  const addCard = async (listId: number) => {
    const v = newTitle.trim(); if (!v) { setAdding(null); return; }
    try { await post('cards/', { list: listId, title: v }); setNewTitle(''); reload(); } catch (e) { toastErr(e); }
  };
  const addList = async () => { const n = prompt('Название колонки'); if (!n) return; try { await post('lists/', { board: b.id, name: n }); reload(); } catch (e) { toastErr(e); } };
  const renameList = async (l: BoardList, name: string) => { setEditList(null); if (!name.trim() || name === l.name) return; try { await patch(`lists/${l.id}/`, { name: name.trim() }); reload(); } catch (e) { toastErr(e); } };
  const reorderLists = async (target: number) => {
    const src = listDrag.current; listDrag.current = null; if (src == null || src === target) return;
    const ids = b.lists.map((l) => l.id).filter((x) => x !== src); ids.splice(ids.indexOf(target), 0, src);
    setB({ ...b, lists: ids.map((id) => b.lists.find((l) => l.id === id)!) });
    try { await post('lists/reorder/', { board: b.id, ids }); } catch (e) { toastErr(e); reload(); }
  };

  return <div className="lists">
    {b.lists.map((l) => {
      const overLimit = l.wip_limit != null && l.cards.length > l.wip_limit;
      return <div key={l.id} className={`list ${over === l.id ? 'over' : ''}`}
        onDragOver={(e) => { if (drag.current) { e.preventDefault(); if (over !== l.id) setOver(l.id); } else if (listDrag.current != null) e.preventDefault(); }}
        onDragLeave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) setOver(null); }}
        onDrop={(e) => { e.preventDefault(); if (drag.current) drop(l.id, l.cards.length); else reorderLists(l.id); }}>
        <div className="lh" draggable={editList !== l.id} onDragStart={(e) => { if (drag.current) return; listDrag.current = l.id; e.dataTransfer.effectAllowed = 'move'; }} onDoubleClick={() => setEditList(l.id)} style={{ cursor: 'grab' }}>
          {editList === l.id ? <input autoFocus defaultValue={l.name} onBlur={(e) => renameList(l, e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} /> : <span>{l.name}</span>}
          <small className={overLimit ? 'r' : ''}>{l.cards.length}{l.wip_limit != null ? ` / ${l.wip_limit}` : ''}</small>
        </div>
        <div className="cards">{l.cards.map((c, i) => <div key={c.id} onDragOver={(e) => { if (drag.current) e.preventDefault(); }} onDrop={(e) => { if (!drag.current) return; e.preventDefault(); e.stopPropagation(); const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); drop(l.id, e.clientY < r.top + r.height / 2 ? i : i + 1); }}>
          <CardTile c={c} labels={b.labels} dragging={dragId === c.id} onOpen={() => onOpen(c.id)}
            onDragStart={(e) => { drag.current = { card: c.id, from: l.id }; setDragId(c.id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(c.id)); }}
            onDragEnd={() => { setDragId(null); setOver(null); }} /></div>)}</div>
        {adding === l.id ? <div className="newc" style={{ marginTop: 6 }}><textarea rows={2} autoFocus placeholder="Название карточки" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCard(l.id); } if (e.key === 'Escape') setAdding(null); }} />
          <div className="row" style={{ marginTop: 4 }}><button className="btn sm" onClick={() => addCard(l.id)}>{t('common.add')}</button><button className="btn ghost sm" onClick={() => { setAdding(null); setNewTitle(''); }}>{t('common.cancel')}</button></div></div>
          : <button className="addc" onClick={() => { setAdding(l.id); setNewTitle(''); }}><Icon name="plus" />Добавить карточку</button>}
      </div>;
    })}
    <div className="list" style={{ background: 'transparent', border: '1.5px dashed var(--dashed)' }}><button className="addc" onClick={addList}><Icon name="plus" />Добавить колонку</button></div>
  </div>;
}

function ListView({ b, onOpen }: { b: Board; onOpen: (id: number) => void }) {
  const rows = b.lists.flatMap((l) => l.cards.map((c) => ({ c, l })));
  if (!rows.length) return <Empty text="Карточек нет" />;
  return <div className="card np"><table><thead><tr><th>Карточка</th><th>Колонка</th><th>Клиент</th><th>Срок</th><th>Приоритет</th><th>Чек-лист</th><th>Участники</th></tr></thead>
    <tbody>{rows.map(({ c, l }) => <tr key={c.id} className="click" onClick={() => onOpen(c.id)}><td><b style={{ fontWeight: 500 }}>{c.title}</b> {c.conflict_status === 'hit' && <span className="tag r">Конфликт</span>}</td><td className="muted">{l.name}</td><td>{c.client_name || '—'}</td>
      <td>{c.due_label ? <span className={`due ${c.due_state || ''}`}>{c.due_label}</span> : '—'}</td><td>{t('prio.' + c.priority)}</td><td>{c.checklist[1] ? `${c.checklist[0]}/${c.checklist[1]}` : '—'}</td><td><Members ids={c.members} /></td></tr>)}</tbody></table></div>;
}
function Members({ ids }: { ids: number[] }) { const { userById } = useApp(); return <div className="row" style={{ gap: 2 }}>{ids.map((i) => { const u = userById(i); return <Ava key={i} initials={u?.initials} name={u?.full_name} />; })}</div>; }

function CalView({ b, onOpen }: { b: Board; onOpen: (id: number) => void }) {
  const [base, setBase] = useState(() => { const d = new Date(); d.setDate(1); return d; });
  const cards = useMemo(() => b.lists.flatMap((l) => l.cards).filter((c) => c.due_at), [b]);
  const start = new Date(base); const wd = (start.getDay() + 6) % 7; start.setDate(1 - wd);
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  const today = ymd(new Date());
  return <>
    <div className="row" style={{ marginBottom: 10 }}><button className="btn ghost sm" onClick={() => { const d = new Date(base); d.setMonth(d.getMonth() - 1); setBase(d); }}><Icon name="left" /></button>
      <b style={{ fontWeight: 600, textTransform: 'capitalize' }}>{base.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })}</b>
      <button className="btn ghost sm" onClick={() => { const d = new Date(base); d.setMonth(d.getMonth() + 1); setBase(d); }}><Icon name="arrow" /></button><span className="muted small">Сроки карточек доски «{b.name}»</span></div>
    <div className="cal">{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((x) => <div key={x} className="dh">{x}</div>)}
      {days.map((d) => { const k = ymd(d); const evs = cards.filter((c) => ymd(new Date(c.due_at!)) === k); return <div key={k} className={`${k === today ? 'today' : ''} ${d.getMonth() !== base.getMonth() ? 'off' : ''}`}><b style={{ fontWeight: k === today ? 700 : 500 }}>{d.getDate()}</b>
        {evs.map((c) => <span key={c.id} className="ev" onClick={() => onOpen(c.id)} style={{ borderColor: c.due_state === 'late' ? 'var(--danger)' : c.due_state === 'soon' ? 'var(--warning)' : 'var(--primary)' }}>{c.title}</span>)}</div>; })}</div>
  </>;
}

function NewBoard({ onClose, onDone }: { onClose: () => void; onDone: (b: Board) => void }) {
  const [name, setName] = useState(''); const [tpl, setTpl] = useState('blank'); const [color, setColor] = useState('#2A47A1');
  const TPL: [string, string][] = [['blank', 'Пустая'], ['leads', 'Лиды'], ['family', 'Семейные дела'], ['criminal', 'Уголовные дела'], ['inner', 'Внутренние задачи']];
  return <Modal small onClose={onClose}><h2>Новая доска</h2>
    <div className="lbl">Название</div><input className="fld" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
    <div className="lbl" style={{ marginTop: 10 }}>Шаблон</div><div className="picker">{TPL.map(([k, l]) => <button key={k} className={tpl === k ? 'on' : ''} onClick={() => { setTpl(k); if (!name || TPL.some((x) => x[1] === name)) setName(k === 'blank' ? '' : l); }}>{l}</button>)}</div>
    <div className="lbl" style={{ marginTop: 10 }}>Цвет</div><div className="row">{['#2A47A1', '#0F766E', '#6D5BD0', '#B7791F', '#64748B', '#D14343'].map((c) => <button key={c} onClick={() => setColor(c)} style={{ width: 24, height: 24, borderRadius: 5, background: c, outline: color === c ? '2px solid var(--text)' : 'none' }} />)}</div>
    <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" disabled={!name.trim()} onClick={async () => { try { onDone(await post<Board>('boards/', { name: name.trim(), template: tpl, color })); toast('Доска создана'); } catch (e) { toastErr(e); } }}>{t('common.create')}</button></div>
  </Modal>;
}

function TrelloImport({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null); const [busy, setBusy] = useState(false); const [rep, setRep] = useState<any>(null);
  return <Modal small onClose={onClose}><h2>Импорт из Trello</h2>
    <div className="note" style={{ marginBottom: 12 }}><Icon name="info" /><div>Trello → меню доски → «Печать, экспорт и общий доступ» → «Экспорт в JSON». Переносятся колонки, карточки, описания, чек-листы, метки, комментарии и вложения-ссылки. Пользователи сопоставляются по имени и логину.</div></div>
    <input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] || null)} />
    {rep && <div className="card" style={{ marginTop: 12 }}><h3>Отчёт сверки</h3>
      <div className="kv">{['boards', 'lists', 'cards', 'checklists', 'comments', 'labels'].map((k) => <Fragment key={k}><span>{({ boards: 'Доски', lists: 'Колонки', cards: 'Карточки', checklists: 'Чек-листы', comments: 'Комментарии', labels: 'Метки' } as any)[k]}</span><b>{rep[k] ?? 0}</b></Fragment>)}</div>
      {rep.unmatched_users?.length > 0 && <div className="note w"><Icon name="alert" /><div>Не сопоставлены пользователи Trello: {rep.unmatched_users.join(', ')}. Их действия записаны без автора.</div></div>}</div>}
    <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.close')}</button>
      <button className="btn" disabled={!file || busy} onClick={async () => { setBusy(true); try { setRep(await upload('boards/import-trello/', { file })); toast('Импорт завершён'); onDone(); } catch (e) { toastErr(e); } finally { setBusy(false); } }}>{busy ? 'Импорт…' : 'Импортировать'}</button></div>
  </Modal>;
}

const ACT: Record<Automation['action'], string> = { assign: 'Назначить ответственного', set_due_days: 'Поставить срок (дней)', add_checklist: 'Добавить чек-лист', notify: 'Отправить уведомление', set_case_status: 'Изменить статус дела' };
function BoardSettings({ b, onClose, onChanged }: { b: Board; onClose: () => void; onChanged: (archived?: boolean) => void }) {
  const { user, dict } = useApp();
  const [name, setName] = useState(b.name);
  const autos = useLoad(() => get<Automation[]>(`automations/?board=${b.id}`), [b.id]);
  const [na, setNa] = useState<{ list: number; action: Automation['action']; value: string; user: number | null }>({ list: b.lists[0]?.id, action: 'assign', value: '', user: null });
  const upd = async (body: any, msg: string, archived?: boolean) => { try { await patch(`boards/${b.id}/`, body); toast(msg); onChanged(archived); } catch (e) { toastErr(e); } };
  const listUpd = async (id: number, body: any) => { try { await patch(`lists/${id}/`, body); onChanged(); } catch (e) { toastErr(e); } };
  const addAuto = async () => {
    const params: any = na.action === 'assign' ? { user: na.user } : na.action === 'set_due_days' ? { days: Number(na.value) || 1 } : na.action === 'add_checklist' ? { title: na.value || 'Чек-лист', items: [] } : na.action === 'notify' ? { user: na.user, text: na.value } : { status: na.value };
    try { await post('automations/', { board: b.id, list: na.list, action: na.action, params, is_active: true }); autos.reload(true); toast('Правило добавлено'); } catch (e) { toastErr(e); }
  };
  return <Modal onClose={onClose}><h2>Настройки доски</h2>
    <div className="grid g2">
      <div>
        <div className="lbl">Название</div><div className="row"><input className="fld" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn sm" onClick={() => upd({ name }, 'Доска переименована')}>{t('common.save')}</button></div>
        <div className="row wrap" style={{ marginTop: 12 }}>
          <button className="btn ghost sm" onClick={() => upd({ is_favorite: !b.is_favorite }, b.is_favorite ? 'Убрано из избранного' : 'Добавлено в избранное')}><Icon name="star" />{b.is_favorite ? 'Убрать из избранного' : 'В избранное'}</button>
          <button className="btn ghost sm" onClick={async () => { try { await post(`boards/${b.id}/copy/`); toast('Копия доски создана'); onChanged(); } catch (e) { toastErr(e); } }}><Icon name="copy" />Копировать</button>
          <button className="btn ghost sm" onClick={() => confirm('Архивировать доску?') && upd({ is_archived: true }, 'Доска в архиве', true)}><Icon name="archive" />Архивировать</button>
        </div>
        <h3 style={{ marginTop: 18 }}>Колонки</h3>
        {b.lists.map((l) => <div key={l.id} className="set"><div>{l.name}<small>{l.is_final ? 'Итоговая колонка: перенос AI — с подтверждением' : 'Обычная колонка'}</small></div>
          <div className="row"><input className="fld" style={{ width: 70 }} type="number" min={0} placeholder="лимит" defaultValue={l.wip_limit ?? ''} onBlur={(e) => listUpd(l.id, { wip_limit: e.target.value ? Number(e.target.value) : null })} title="Лимит карточек" />
            <span className="small muted">итог.</span><input type="checkbox" checked={l.is_final} onChange={() => listUpd(l.id, { is_final: !l.is_final })} />
            <button className="ib" title="Архивировать колонку" onClick={() => confirm(`Архивировать колонку «${l.name}»?`) && listUpd(l.id, { is_archived: true })}><Icon name="archive" /></button></div></div>)}
      </div>
      <div>
        <h3>Автоматизации</h3><div className="muted small" style={{ marginBottom: 8 }}>При переносе карточки в колонку выполняется действие.</div>
        {autos.data?.length ? autos.data.map((a) => <div key={a.id} className="set"><div>«{b.lists.find((l) => l.id === a.list)?.name}» → {ACT[a.action]}<small>{JSON.stringify(a.params)}</small></div>
          {user.role === 'admin' && <button className="ib" onClick={async () => { try { await del(`automations/${a.id}/`); autos.reload(true); } catch (e) { toastErr(e); } }}><Icon name="x" /></button>}</div>) : <div className="muted small">Правил нет</div>}
        {user.role === 'admin' ? <div className="card" style={{ marginTop: 10, padding: 12 }}>
          <div className="fg"><div><div className="lbl">Колонка</div><select className="fld" value={na.list} onChange={(e) => setNa({ ...na, list: Number(e.target.value) })}>{b.lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></div>
            <div><div className="lbl">Действие</div><select className="fld" value={na.action} onChange={(e) => setNa({ ...na, action: e.target.value as any, value: '' })}>{Object.entries(ACT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
            {(na.action === 'assign' || na.action === 'notify') && <div><div className="lbl">Сотрудник</div><UserSelect value={na.user} onChange={(v) => setNa({ ...na, user: v })} /></div>}
            {na.action === 'set_case_status' ? <div><div className="lbl">Статус дела</div><select className="fld" value={na.value} onChange={(e) => setNa({ ...na, value: e.target.value })}><option value="">—</option>{dict.case_status.map((s) => <option key={s.id} value={s.code}>{s.name}</option>)}</select></div>
              : na.action !== 'assign' && <div><div className="lbl">{na.action === 'set_due_days' ? 'Дней' : na.action === 'notify' ? 'Текст' : 'Название чек-листа'}</div><input className="fld" value={na.value} onChange={(e) => setNa({ ...na, value: e.target.value })} /></div>}</div>
          <button className="btn sm" style={{ marginTop: 10 }} onClick={addAuto}><Icon name="plus" />Добавить правило</button></div> : <div className="muted small" style={{ marginTop: 8 }}>Правила настраивает администратор.</div>}
      </div>
    </div>
  </Modal>;
}
