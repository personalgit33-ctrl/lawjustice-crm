'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { get, post, upload } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { DueTag, Empty, Modal, View, useLoad, Ava } from '@/components/ui';
import { UserSelect, pickFiles } from '@/components/common';
import { toast, toastErr } from '@/components/toast';
import { fromLocalInput, ymd } from '@/lib/format';
import { t } from '@/i18n';
import type { Deadline, DeadlineState } from '@/lib/types';
import { NewDeadline } from '@/components/NewDeadline';

type F = 'active' | DeadlineState;
export default function DeadlinesPage() {
  const [f, setF] = useState<F>('active');
  const [userF, setUserF] = useState<number | null>(null);
  const [add, setAdd] = useState(false);
  const counts = useLoad(() => get<Record<string, number>>('deadlines/counts/'));
  const s = useLoad(() => get<Deadline[]>(`deadlines/?state=${f}${userF ? '&user=' + userF : ''}`), [f, userF]);
  const reload = () => { s.reload(true); counts.reload(true); };
  const done = async (d: Deadline) => {
    const attach = confirm('Приложить подтверждающий документ?');
    let file: File | undefined; if (attach) [file] = await pickFiles(false);
    try { await upload(`deadlines/${d.id}/done/`, { file }); toast('Срок отмечен выполненным'); reload(); } catch (e) { toastErr(e); }
  };
  const F_: [F, string][] = [['active', 'dl.active'], ['late', 'dl.late'], ['today', 'dl.today'], ['week', 'dl.week'], ['done', 'dl.done']];
  return <>
    <div className="bhead"><div className="seg">{F_.map(([k, l]) => <button key={k} className={f === k ? 'on' : ''} onClick={() => setF(k)}>{t(l)} <span className="muted">{counts.data?.[k] ?? ''}</span></button>)}</div>
      <div style={{ width: 200 }}><UserSelect value={userF} onChange={setUserF} empty="Все юристы" /></div>
      <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => setAdd(true)}><Icon name="plus" />Добавить срок</button></div>
    <div className="note" style={{ marginBottom: 12 }}><Icon name="bell" /><div>Напоминания ответственному и дублирующему — за 7, 3 и 1 день и в день срока. Срок без отметки о выполнении эскалируется руководителю.</div></div>
    <View s={s}>{(list) => <div className="card np"><table><thead><tr><th>Срок</th><th>Событие</th><th>Дело</th><th>Суд / орган</th><th>Основание</th><th>Ответственный / дубль</th><th>Статус</th><th></th></tr></thead><tbody>
      {list.length === 0 ? <tr><td colSpan={8}><Empty text="Нет сроков" /></td></tr> : list.map((d) => <tr key={d.id}>
        <td style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>{d.due_label}</td><td>{d.title}<div className="muted small">{d.type_label}</div></td>
        <td>{d.case ? <Link className="lnk" href={`/cases/${d.case}`}>{d.case_label}</Link> : d.case_label || '—'}{d.is_confidential && <> <Icon name="lock" size={12} /></>}</td>
        <td className="small">{d.court || '—'}{d.room && `, ${d.room}`}{d.judge && <div className="muted">Судья {d.judge}</div>}</td><td className="small muted">{d.basis}</td>
        <td><div className="row"><U id={d.responsible} /><U id={d.backup} /></div></td><td><DueTag s={d.state} /></td>
        <td>{d.state !== 'done' ? <button className="btn ghost sm" onClick={() => done(d)}><Icon name="ok" />Выполнено</button> : d.done_file ? <a className="lnk small" href={d.done_file.url} target="_blank" rel="noreferrer"><Icon name="clip" size={12} /> документ</a> : null}</td></tr>)}
    </tbody></table></div>}</View>
    {add && <NewDeadline onClose={() => setAdd(false)} onDone={() => { setAdd(false); reload(); }} />}
  </>;
}
function U({ id }: { id: number | null }) { const { userById } = useApp(); const u = userById(id); return u ? <Ava initials={u.initials} name={u.full_name} /> : null; }

