'use client';
import { useEffect, useState } from 'react';
import { get, post } from '@/lib/api';
import { useApp } from './AppContext';
import { Icon } from './Icon';
import { Modal } from './ui';
import { UserSelect } from './common';
import { toast, toastErr } from './toast';
import { fromLocalInput, ymd } from '@/lib/format';
import { t } from '@/i18n';
import type { Case } from '@/lib/types';

export function NewDeadline({ onClose, onDone, caseId }: { onClose: () => void; onDone: () => void; caseId?: number }) {
  const { dict, user } = useApp();
  const [cases, setCases] = useState<Case[]>([]);
  const [v, setV] = useState({ type: 'procedural', case: caseId ?? null as number | null, title: '', court: '', judge: '', room: '', basis: '', responsible: user.id as number | null, backup: null as number | null, due: '' });
  const [base, setBase] = useState(ymd(new Date())); const [tpl, setTpl] = useState<number | ''>('');
  useEffect(() => { get<Case[]>('cases/').then(setCases).catch(() => {}); }, []);
  useEffect(() => { const c = cases.find((x) => x.id === v.case); if (c && !v.court) setV((o) => ({ ...o, court: c.court })); }, [v.case, cases]); // eslint-disable-line react-hooks/exhaustive-deps
  const calc = async () => {
    if (!tpl || !base) return;
    try { const r = await post<{ date: string }>('deadlines/calc/', { base_date: base, template_id: tpl }); setV((o) => ({ ...o, due: `${r.date.slice(0, 10)}T18:00`, basis: o.basis || `Шаблон: ${dict.deadline_template.find((x) => x.id === tpl)?.name}, от ${base}` })); } catch (e) { toastErr(e); }
  };
  useEffect(() => { calc(); }, [tpl, base]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async () => {
    if (!v.title.trim() || !v.due) { toast('Укажите событие и дату', true); return; }
    try { await post('deadlines/', { ...v, due_at: fromLocalInput(v.due) }); toast('Срок добавлен · напоминания настроены'); onDone(); } catch (e) { toastErr(e); }
  };
  const TYPES: [string, string][] = [['hearing', 'Судебное заседание'], ['procedural', 'Подача документа / жалобы'], ['execution', 'Срок исполнения'], ['contract', 'Договорный'], ['internal', 'Внутренний']];
  return <Modal small onClose={onClose}><h2>Новый срок</h2>
    <div className="fg">
      <div><div className="lbl">Тип</div><select className="fld" value={v.type} onChange={(e) => setV({ ...v, type: e.target.value })}>{TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      <div><div className="lbl">Дело</div><select className="fld" value={v.case ?? ''} onChange={(e) => setV({ ...v, case: e.target.value ? Number(e.target.value) : null })}><option value="">—</option>{cases.map((c) => <option key={c.id} value={c.id}>{c.number} · {c.client_name}</option>)}</select></div>
      <div className="full"><div className="lbl">Событие</div><input className="fld" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} placeholder="Например: апелляционная жалоба" /></div>
      <div><div className="lbl">Дата основания (получение документа)</div><input className="fld" type="date" value={base} onChange={(e) => setBase(e.target.value)} /></div>
      <div><div className="lbl">Шаблон срока</div><select className="fld" value={tpl} onChange={(e) => setTpl(e.target.value ? Number(e.target.value) : '')}><option value="">Без шаблона</option>{dict.deadline_template.map((d) => <option key={d.id} value={d.id}>{d.name} — {String(d.extra?.days ?? '')} дн.</option>)}</select></div>
      <div className="full"><div className="lbl">Дата и время срока</div><input className="fld" type="datetime-local" value={v.due} onChange={(e) => setV({ ...v, due: e.target.value })} /></div>
      <div><div className="lbl">Суд / орган</div><input className="fld" value={v.court} onChange={(e) => setV({ ...v, court: e.target.value })} /></div>
      <div><div className="lbl">Судья</div><input className="fld" value={v.judge} onChange={(e) => setV({ ...v, judge: e.target.value })} /></div>
      <div><div className="lbl">Зал</div><input className="fld" value={v.room} onChange={(e) => setV({ ...v, room: e.target.value })} /></div>
      <div><div className="lbl">Основание</div><input className="fld" value={v.basis} onChange={(e) => setV({ ...v, basis: e.target.value })} /></div>
      <div><div className="lbl">Ответственный</div><UserSelect value={v.responsible} onChange={(x) => setV({ ...v, responsible: x })} /></div>
      <div><div className="lbl">Дублирующий</div><UserSelect value={v.backup} onChange={(x) => setV({ ...v, backup: x })} /></div>
    </div>
    <div className="note" style={{ marginTop: 12 }}><Icon name="clock" /><div>Шаблоны сроков ведёт компания; система норм законодательства не содержит, итоговую дату подтверждает юрист.</div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button><button className="btn" onClick={save}>{t('common.save')}</button></div>
  </Modal>;
}
