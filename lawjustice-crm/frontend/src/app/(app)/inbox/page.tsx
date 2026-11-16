'use client';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { get, post, upload, fileUrl } from '@/lib/api';
import { useEvents } from '@/lib/ws';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { ChTag, CfTag, Empty, ErrorState, Loading, Modal, Seg, useLoad } from '@/components/ui';
import { UserSelect, pickFiles } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { initials, time } from '@/lib/format';
import { t } from '@/i18n';
import type { Attachment, CardDetail, Case, Conversation, ConversationDetail, ConvMode, Message } from '@/lib/types';

const FILTERS: [string, string][] = [['all', 'conv.f.all'], ['urgent', 'conv.f.urgent'], ['ai', 'conv.f.ai'], ['unread', 'conv.f.unread'], ['wa', 'ch.wa'], ['g', 'ch.g'], ['meta', 'ch.meta'], ['ph', 'nav.calls'], ['closed', 'conv.f.closed']];
const winLabel = (s: number | null) => s == null ? null : s <= 0 ? 'закрыто — только шаблон' : `${Math.floor(s / 3600)} ч ${Math.floor((s % 3600) / 60)} мин`;

export default function InboxPage() { return <Suspense fallback={<Loading />}><Inbox /></Suspense>; }

function Inbox() {
  const sp = useSearchParams();
  const router = useRouter();
  const { refreshCounters } = useApp();
  const [filter, setFilter] = useState('all');
  const [sel, setSel] = useState<number | null>(sp.get('c') ? Number(sp.get('c')) : null);
  const [info, setInfo] = useState(false);
  const list = useLoad(() => get<Conversation[]>(`conversations/?filter=${filter}`), [filter]);
  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [cErr, setCErr] = useState<any>(null);

  useEffect(() => { if (sel == null && list.data?.length && window.innerWidth > 760) setSel(list.data[0].id); }, [list.data, sel]);
  const loadConv = async (id: number, silent = false) => {
    if (!silent) { setConv(null); setCErr(null); }
    try { const d = await get<ConversationDetail>(`conversations/${id}/`); setConv(d); list.setData((a) => a ? a.map((c) => c.id === id ? { ...c, unread: 0 } : c) : a); refreshCounters(); }
    catch (e) { setCErr(e); }
  };
  useEffect(() => { if (sel != null) loadConv(sel); }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps

  useEvents((e) => {
    if (e.type === 'message.new') {
      const cid = e.payload?.conversation ?? e.payload?.conversation_id;
      const m: Message | undefined = e.payload?.message;
      if (cid === sel && m) setConv((c) => c && !c.messages.some((x) => x.id === m.id) ? { ...c, messages: [...c.messages, m] } : c);
      if (cid === sel) loadConv(sel!, true);
      list.reload(true);
    }
    if (e.type === 'conversation.updated') { list.reload(true); if (e.payload?.id === sel) loadConv(sel!, true); }
  }, [sel, filter]);

  const replace = (d: ConversationDetail) => { setConv(d); list.setData((a) => a ? a.map((c) => c.id === d.id ? { ...c, ...d } : c) : a); };

  return <div className={`inbox ${sel != null ? 'open' : ''} ${info ? 'info' : ''}`}>
    <div className="clist">
      <div className="cfil">{FILTERS.map(([k, l]) => <button key={k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>{t(l)}</button>)}</div>
      <div style={{ overflow: 'auto', flex: 1 }}>
        {list.loading && !list.data ? <Loading /> : list.error && !list.data ? <ErrorState error={list.error} retry={list.reload} /> : !list.data?.length ? <Empty text="Обращений нет" /> :
          list.data.map((c) => <div key={c.id} className={`citem ${sel === c.id ? 'on' : ''}`} onClick={() => { setSel(c.id); router.replace(`/inbox?c=${c.id}`); }}>
            <div className="ava">{initials(c.client_name)}</div>
            <div className="t"><div className="row" style={{ justifyContent: 'space-between', color: 'var(--text)' }}><b style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.client_name}</b><small className="muted">{c.last_label}</small></div>
              <div>{c.last_message}</div>
              <div className="row" style={{ marginTop: 5 }}><ChTag c={c.channel} />{c.urgent && <span className="tag r">Срочно</span>}{c.mode === 'ai' ? <span className="tag b">{t('common.assistant')}</span> : c.mode === 'draft' ? <span className="tag b">Черновик</span> : null}{c.status === 'closed' && <span className="tag">Закрыт</span>}{c.unread ? <span className="unread" style={{ marginLeft: 'auto' }}>{c.unread}</span> : null}</div></div>
          </div>)}
      </div>
    </div>
    {sel == null ? <div className="conv"><Empty text="Выберите диалог" /></div> :
      cErr ? <div className="conv"><ErrorState error={cErr} retry={() => loadConv(sel)} /></div> :
      !conv ? <div className="conv"><Loading /></div> :
      <Chat conv={conv} onBack={() => { setSel(null); router.replace('/inbox'); }} onInfo={() => setInfo(!info)} replace={replace} reload={() => loadConv(conv.id, true)} />}
    {conv && <ClientPanel conv={conv} replace={replace} onClose={() => setInfo(false)} />}
  </div>;
}

function Chat({ conv: c, onBack, onInfo, replace, reload }: { conv: ConversationDetail; onBack: () => void; onInfo: () => void; replace: (d: ConversationDetail) => void; reload: () => void }) {
  const { dict } = useApp();
  const [text, setText] = useState('');
  const [note, setNote] = useState(false);
  const [file, setFile] = useState<Attachment | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [preview, setPreview] = useState<Attachment | null>(null);
  useEffect(() => { box.current && (box.current.scrollTop = box.current.scrollHeight); }, [c.messages.length, c.id]);
  useEffect(() => { setText(''); setFile(null); setDraft(null); setNote(false); }, [c.id]);
  const winClosed = c.channel === 'wa' && c.wa_window_seconds === 0;

  const setMode = async (m: ConvMode) => { if (m === c.mode) return; try { replace(await post(`conversations/${c.id}/mode/`, { mode: m })); } catch (e) { toastErr(e); } };
  const attach = async () => {
    const [f] = await pickFiles(false); if (!f) return;
    try { setBusy(true); setFile(await upload<Attachment>('attachments/', { file: f, conversation: c.id })); } catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  const send = async () => {
    const v = text.trim(); if (!v && !file) return;
    setBusy(true);
    try {
      await post<Message>(`conversations/${c.id}/messages/`, { text: v, attachment: file?.id, is_note: note || undefined });
      setText(''); setFile(null); reload();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  };
  const sendDraft = async () => { try { replace(await post(`conversations/${c.id}/send-draft/`, draft != null ? { text: draft } : {})); setDraft(null); toast('Черновик отправлен клиенту'); } catch (e) { toastErr(e); } };
  const rate = async (m: Message, v: boolean) => { try { const r = await post<Message>(`messages/${m.id}/rate/`, { correct: v }); replace({ ...c, messages: c.messages.map((x) => x.id === m.id ? r : x) }); } catch (e) { toastErr(e); } };
  const toCard = async (m: Message) => {
    const cards = c.related.cards;
    if (!cards.length) { toast('Сначала создайте карточку из диалога', true); return; }
    const card = cards.length === 1 ? cards[0].id : Number(prompt('ID карточки:\n' + cards.map((x) => `${x.id} — ${x.title}`).join('\n'), String(cards[0].id)));
    if (!card) return;
    try { await post(`messages/${m.id}/to-card/`, { card }); toast('Файл прикреплён к карточке'); } catch (e) { toastErr(e); }
  };
  const call = async () => { try { await post('calls/originate/', { phone: c.phone, client: c.client }); toast(`Звонок ${c.phone} через IP-телефонию`); } catch (e) { toastErr(e); } };
  const win = winLabel(c.wa_window_seconds);

  return <div className="conv">
    <div className="chead">
      <button className="ib back" onClick={onBack} aria-label={t('common.back')}><Icon name="left" /></button>
      <b style={{ fontWeight: 600 }}>{c.client_name}</b><ChTag c={c.channel} /><span className="muted small">{c.phone}</span>
      {win && <span className={`tag ${winClosed ? 'a' : ''}`} title="24-часовое окно WhatsApp для свободного ответа"><Icon name="clock" />Окно: {win}</span>}
      <div style={{ marginLeft: 'auto' }}><Seg<ConvMode> value={c.mode} onChange={setMode} options={[['ai', t('conv.mode.ai')], ['draft', t('conv.mode.draft')], ['op', t('conv.mode.op')]]} /></div>
      <button className="ib" onClick={call} title="Позвонить"><Icon name="phone" /></button>
      <button className="ib" onClick={onInfo} title="Клиент"><Icon name="info" /></button>
    </div>
    <div className="msgs" ref={box}>
      {c.messages.map((m) => m.author === 'sys' ? <div key={m.id} className="m sys">{m.text}</div> :
        <div key={m.id} className={`m ${m.author === 'client' ? '' : m.author === 'note' ? 'note' : 'out'}`}>
          {m.author === 'ai' && <div className="who">{t('common.assistant')}{m.template ? ' · шаблон WhatsApp' : ''}</div>}
          {m.author === 'op' && <div className="who">{m.author_name || 'Сотрудник'}</div>}
          {m.author === 'note' && <div className="who">Внутренняя заметка · {m.author_name}</div>}
          {m.text}
          {m.attachment && <div className="file">
            {m.attachment.is_image ? <img src={fileUrl(m.attachment.url)} alt={m.attachment.name} onClick={() => setPreview(m.attachment)} /> : <Icon name="file" style={{ color: 'var(--text-secondary)' }} />}
            <a href={fileUrl(m.attachment.url)} target="_blank" rel="noreferrer" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.attachment.name}</a>
            <button className="btn ghost sm" style={{ marginLeft: 'auto' }} onClick={() => toCard(m)}>В карточку</button></div>}
          <small>{m.author === 'ai' && <><button className={m.rating === true ? 'on' : ''} onClick={() => rate(m, true)}>верно</button><button className={m.rating === false ? 'on' : ''} onClick={() => rate(m, false)}>неверно</button></>}
            {time(m.created_at)}{m.author !== 'client' && m.author !== 'note' && m.delivery ? ' · ' + ({ sent: 'отправлено', delivered: 'доставлено', read: 'прочитано', failed: 'не доставлено' } as any)[m.delivery] : ''}</small>
        </div>)}
    </div>
    {c.mode === 'draft' && c.draft && <div className="draft"><div className="lbl" style={{ color: 'var(--primary)', fontWeight: 600 }}>Черновик ассистента — проверьте перед отправкой</div>
      {draft == null ? <div>{c.draft}</div> : <textarea className="fld" rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} />}
      <div className="row wrap" style={{ marginTop: 8 }}><button className="btn sm" onClick={sendDraft}><Icon name="send" />Отправить</button>{draft == null && <button className="btn ghost sm" onClick={() => setDraft(c.draft)}>Изменить</button>}<span className="muted small" style={{ marginLeft: 'auto' }}>Режим «Черновик» включается на период запуска</span></div></div>}
    <div className="quick">{dict.quick_reply.map((q) => <button key={q.id} onClick={() => setText(String(q.extra?.text || q.name))}>{q.name}</button>)}
      <button onClick={() => setNote(!note)} style={note ? { borderColor: 'var(--warning-border)', background: 'var(--warning-bg)', color: 'var(--warning-text)' } : undefined}><Icon name="note" size={12} /> Заметка</button></div>
    {file && <div className="pending row"><Icon name="clip" size={13} />{file.name}<button className="btn link small" onClick={() => setFile(null)}>убрать</button></div>}
    {winClosed && !note && <div className="pending" style={{ color: 'var(--warning-text)' }}>24-часовое окно закрыто: свободный ответ недоступен, отправьте одобренный шаблон.</div>}
    <div className={`comp ${note ? 'note-mode' : ''}`}>
      <button className="ib" onClick={attach} disabled={busy} title="Прикрепить фото или документ"><Icon name="clip" /></button>
      <input type="text" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
        placeholder={note ? 'Внутренняя заметка — клиент её не увидит' : c.mode === 'ai' ? 'Ведёт ассистент — начните писать, чтобы забрать диалог' : `Сообщение клиенту · ${({ wa: 'WhatsApp', g: 'Google', meta: 'Meta', ph: 'Телефония' } as any)[c.channel] || 'канал'}`} />
      <button className="btn" onClick={send} disabled={busy}><Icon name="send" />{note ? 'Заметка' : t('common.send')}</button>
    </div>
    {preview && <div className="preview" onClick={() => setPreview(null)}><img src={fileUrl(preview.url)} alt={preview.name} /></div>}
  </div>;
}

function ClientPanel({ conv: c, replace, onClose }: { conv: ConversationDetail; replace: (d: ConversationDetail) => void; onClose: () => void }) {
  const router = useRouter();
  const { dict } = useApp();
  const [assign, setAssign] = useState(false);
  const [close, setClose] = useState(false);
  const createCard = async () => { try { const card = await post<CardDetail>(`conversations/${c.id}/create-card/`); toast(`Карточка создана на доске «${card.board_name}»`); router.push(`/boards?board=${card.board}&card=${card.id}`); } catch (e) { toastErr(e); } };
  const createCase = async () => { try { const cs = await post<Case>(`conversations/${c.id}/create-case/`); toast(`Дело № ${cs.number} создано`); router.push(`/cases/${cs.id}`); } catch (e: any) { toast(e.status === 409 ? (e.message || 'Нельзя создать дело: требуется решение по конфликту интересов') : e.message, true); } };
  return <div className="cinfo">
    <div className="row" style={{ marginBottom: 12 }}><h3 style={{ margin: 0 }}>Клиент</h3><button className="ib" style={{ marginLeft: 'auto' }} onClick={onClose}><Icon name="x" /></button></div>
    <div className="kv"><span>Имя</span><Link className="lnk" href={`/clients/${c.client}`}>{c.client_name}</Link><span>Телефон</span><div>{c.phone}</div><span>Источник</span><div>{c.source_label}</div><span>Этап</span><div>{c.stage || '—'}</div><span>Ответств.</span><div>{c.responsible_name || '—'}</div>
      <span>Согласие ПД</span><div>{c.consent_ok ? c.consent_label : <span className="tag a">{c.consent_label || 'Не получено'}</span>}</div></div>
    <div style={{ marginBottom: 12 }}><CfTag s={c.conflict_status} /></div>
    {c.summary && <div className="sum"><b>Резюме обращения</b><div style={{ marginTop: 4 }}>{c.summary}</div></div>}
    <button className="btn w100" onClick={createCard}><Icon name="plus" />Создать карточку</button>
    <button className="btn ghost w100" onClick={createCase}><Icon name="case" />Создать дело</button>
    <button className="btn ghost w100" onClick={() => setAssign(true)}><Icon name="arrow" />Назначить / передать</button>
    {c.status !== 'closed' && <button className="btn ghost w100" onClick={() => setClose(true)}>Закрыть с результатом</button>}
    <h3 style={{ marginTop: 16 }}>Связанное</h3>
    <div className="small muted" style={{ lineHeight: 1.9 }}>
      {c.related.cards.map((x) => <div key={x.id}><Icon name="boards" size={13} /> <Link className="lnk" href={`/boards?card=${x.id}`}>{x.title}</Link> · {x.board_name}</div>)}
      {c.related.cases.map((x) => <div key={x.id}><Icon name="case" size={13} /> <Link className="lnk" href={`/cases/${x.id}`}>№ {x.number}</Link> · {x.title}</div>)}
      <div><Icon name="phone" size={13} /> {c.related.calls} звонк(ов) · <Icon name="file" size={13} /> {c.related.files} файл(ов)</div>
    </div>
    {assign && <AssignModal conv={c} onClose={() => setAssign(false)} onDone={(d) => { replace(d); setAssign(false); toast('Диалог передан'); }} />}
    {close && <CloseModal conv={c} reasons={dict.refusal_reason.map((r) => r.name)} onClose={() => setClose(false)} onDone={(d) => { replace(d); setClose(false); toast('Диалог закрыт'); }} />}
  </div>;
}

function AssignModal({ conv, onClose, onDone }: { conv: Conversation; onClose: () => void; onDone: (d: ConversationDetail) => void }) {
  const [u, setU] = useState<number | null>(conv.responsible);
  return <Modal small onClose={onClose}><h2>Назначить ответственного</h2>
    <div className="lbl">Сотрудник</div><UserSelect value={u} onChange={setU} empty="Выберите сотрудника" />
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" disabled={!u} onClick={async () => { try { onDone(await post(`conversations/${conv.id}/assign/`, { user: u })); } catch (e) { toastErr(e); } }}>Назначить</button></div>
  </Modal>;
}
function CloseModal({ conv, reasons, onClose, onDone }: { conv: Conversation; reasons: string[]; onClose: () => void; onDone: (d: ConversationDetail) => void }) {
  const [r, setR] = useState<'client' | 'consult' | 'refused' | 'spam'>('consult');
  const [reason, setReason] = useState(reasons[0] || '');
  return <Modal small onClose={onClose}><h2>Закрыть диалог</h2>
    <div className="lbl">Результат</div>
    <div className="picker" style={{ marginBottom: 12 }}>{(['client', 'consult', 'refused', 'spam'] as const).map((k) => <button key={k} className={r === k ? 'on' : ''} onClick={() => setR(k)}>{t('close.' + k)}</button>)}</div>
    {r === 'refused' && <><div className="lbl">Причина отказа</div><select className="fld" value={reason} onChange={(e) => setReason(e.target.value)}>{reasons.map((x) => <option key={x}>{x}</option>)}</select></>}
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" onClick={async () => { try { onDone(await post(`conversations/${conv.id}/close/`, { result: r, reason: r === 'refused' ? reason : undefined })); } catch (e) { toastErr(e); } }}>{t('common.close')}</button></div>
  </Modal>;
}
