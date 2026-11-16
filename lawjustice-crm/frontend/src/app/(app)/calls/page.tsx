'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { get, post, fileUrl } from '@/lib/api';
import { useEvents } from '@/lib/ws';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { Empty, View, useLoad } from '@/components/ui';
import { toast, toastErr } from '@/components/toast';
import { dur } from '@/lib/format';
import { isManager } from '@/lib/access';
import { t } from '@/i18n';
import type { Call } from '@/lib/types';

export default function CallsPage() {
  const { user } = useApp();
  const s = useLoad(() => get<Call[]>('calls/'));
  const [sel, setSel] = useState<number | null>(null);
  useEvents((e) => { if (e.type === 'call.updated' || e.type === 'call.incoming') s.reload(true); });
  useEffect(() => { if (sel == null && s.data?.length) setSel(s.data[0].id); }, [s.data, sel]);
  const sim = async (missed: boolean) => { try { await post('simulate/call/', { phone: missed ? '+996 777 88 99 00' : '+996 555 12 34 56', missed }); toast(missed ? 'Пропущенный звонок создан' : 'Входящий звонок'); s.reload(true); } catch (e) { toastErr(e); } };
  return <>
    <div className="row wrap" style={{ marginBottom: 14 }}>
      {isManager(user.role) && <><button className="btn" onClick={() => sim(false)}><Icon name="phone" />Симулировать входящий звонок</button><button className="btn ghost" onClick={() => sim(true)}>Симулировать пропущенный</button></>}
      <span className="muted small">Записи доступны ответственному, руководителю и администратору. Каждое прослушивание фиксируется в журнале.</span>
    </div>
    <View s={s}>{(calls) => calls.length === 0 ? <Empty text="Звонков пока нет" /> : <>
      <div className="card np"><table><thead><tr><th></th><th>Клиент</th><th>Кто принял</th><th>Статус</th><th>Время</th><th>Длит.</th><th></th></tr></thead><tbody>
        {calls.map((c) => <tr key={c.id} className="click" onClick={() => setSel(c.id)} style={sel === c.id ? { background: 'var(--primary-lighter)' } : undefined}>
          <td style={{ width: 30, color: c.status === 'missed' ? 'var(--danger)' : 'var(--primary)' }}><Icon name={c.direction === 'in' ? 'in' : 'out'} /></td>
          <td><b style={{ fontWeight: 500 }}>{c.client_name || c.phone}</b>{c.is_confidential && <> <Icon name="lock" size={12} style={{ color: 'var(--text-secondary)' }} /></>}<div className="muted small">{c.phone}</div></td>
          <td>{c.handled_by === 'ai' ? <span className="tag b">{t('common.assistant')}</span> : c.handled_by_name || '—'}</td>
          <td><span className={`tag ${c.status === 'missed' ? 'r' : c.status === 'ringing' ? 'a' : 'g'}`}>{t('call.' + c.status)}</span></td>
          <td className="muted">{c.started_label}</td><td>{dur(c.duration)}</td>
          <td style={{ textAlign: 'right' }}><button className="btn ghost sm" onClick={(e) => { e.stopPropagation(); setSel(c.id); }}>{t('common.open')}</button></td></tr>)}
      </tbody></table></div>
      {sel != null && <CallCard id={sel} key={sel} />}
    </>}</View>
  </>;
}

function CallCard({ id }: { id: number }) {
  const s = useLoad(() => get<Call>(`calls/${id}/`), [id]);
  const [audio, setAudio] = useState<string | null>(null);
  const rec = async (action: 'play' | 'download') => {
    try { const r = await post<{ url: string }>(`calls/${id}/recording/`, { action });
      if (action === 'play') { setAudio(fileUrl(r.url)); toast('Воспроизведение записи · действие записано в журнал'); }
      else { const a = document.createElement('a'); a.href = fileUrl(r.url); a.download = `call-${id}`; a.target = '_blank'; a.click(); toast('Скачивание записи · действие записано в журнал'); }
    } catch (e) { toastErr(e); }
  };
  const recall = async (c: Call) => { try { await post('calls/originate/', { phone: c.phone, client: c.client }); toast(`Звонок ${c.phone} через IP-телефонию`); } catch (e) { toastErr(e); } };
  return <div className="card" style={{ marginTop: 14 }}><View s={s}>{(c) => <>
    <div className="row wrap"><b style={{ fontWeight: 600 }}>{c.direction === 'in' ? 'Входящий' : 'Исходящий'} · {c.client_name || c.phone}</b><span className="muted">{c.started_label}</span>
      {c.is_confidential && <span className="tag"><Icon name="lock" />Конфиденциальное дело</span>}
      <div style={{ marginLeft: 'auto' }} className="row">{c.client && <Link className="btn ghost sm" href={`/clients/${c.client}`}>Карточка клиента</Link>}
        <button className="btn sm" onClick={() => recall(c)}><Icon name="phone" />{c.status === 'missed' ? 'Перезвонить' : 'Позвонить'}</button></div></div>
    {c.has_recording && <div className="player" style={{ margin: '12px 0' }}>
      {audio ? <audio src={audio} controls autoPlay /> : <><button onClick={() => rec('play')} style={{ color: 'var(--primary)' }} title="Прослушать"><Icon name="play" /></button><div className="wave" /><span className="small">{dur(c.duration)}</span></>}
      <button onClick={() => rec('download')} className="muted" title="Скачать"><Icon name="dl" /></button></div>}
    {c.summary && <div className="sum" style={{ margin: '10px 0 0' }}><b>Резюме разговора</b><div style={{ marginTop: 4 }}>{c.summary}</div></div>}
    {c.transcript.length > 0 && <details style={{ marginTop: 10 }}><summary style={{ cursor: 'pointer', color: 'var(--primary)', fontWeight: 500 }}>Расшифровка</summary>
      <div style={{ marginTop: 8 }}>{c.transcript.map((r, i) => <p key={i} style={{ margin: '5px 0' }}><b style={{ fontWeight: 600 }}>{r.speaker}:</b> {r.text}</p>)}</div></details>}
    {!c.has_recording && !c.summary && <div className="muted small" style={{ marginTop: 8 }}>Записи нет</div>}
  </>}</View></div>;
}
