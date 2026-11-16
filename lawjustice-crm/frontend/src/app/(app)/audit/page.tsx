'use client';
import { useState } from 'react';
import { get, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Empty, Seg, View, useLoad } from '@/components/ui';
import { toast, toastErr } from '@/components/toast';
import { dt } from '@/lib/format';
import { t } from '@/i18n';
import type { AuditEntry } from '@/lib/types';

const TYPES = ['', 'view', 'export', 'ai', 'record', 'access', 'change', 'check'] as const;
const LIMIT = 50;
export default function AuditPage() {
  const { user } = useApp();
  const [type, setType] = useState<string>(''); const [page, setPage] = useState(0);
  const s = useLoad(() => get<{ count: number; results: AuditEntry[] }>(`audit/?type=${type}&limit=${LIMIT}&offset=${page * LIMIT}`), [type, page]);
  const undo = async (a: AuditEntry) => { if (!confirm('Отменить действие ассистента?')) return; try { await post(`ai/undo/${a.id}/`); toast('Действие отменено'); s.reload(true); } catch (e) { toastErr(e); } };
  return <>
    <div className="bhead"><Seg value={type} onChange={(v) => { setType(v); setPage(0); }} options={TYPES.map((k) => [k, k ? t('audit.' + k) : t('common.all')])} /></div>
    <View s={s}>{(d) => <>
      <div className="card np"><table><thead><tr><th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Тип</th><th></th></tr></thead><tbody>
        {d.results.length === 0 ? <tr><td colSpan={6}><Empty text="Записей нет" /></td></tr> : d.results.map((r) => <tr key={r.id}><td className="muted small" style={{ whiteSpace: 'nowrap' }}>{dt(r.created_at)}</td><td>{r.is_ai ? <span className="tag b">{t('common.assistant')}</span> : r.actor_name}</td><td>{r.action}</td><td className="muted">{r.object_label}</td><td><span className="tag">{r.type_label || t('audit.' + r.type)}</span></td>
          <td>{r.can_undo && user.role === 'admin' && <button className="btn ghost sm" onClick={() => undo(r)}>Отменить</button>}</td></tr>)}</tbody></table></div>
      {d.count > LIMIT && <div className="row" style={{ marginTop: 12, justifyContent: 'center' }}><button className="btn ghost sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Назад</button><span className="muted small">{page * LIMIT + 1}–{Math.min(d.count, (page + 1) * LIMIT)} из {d.count}</span><button className="btn ghost sm" disabled={(page + 1) * LIMIT >= d.count} onClick={() => setPage(page + 1)}>Далее</button></div>}
    </>}</View>
  </>;
}
