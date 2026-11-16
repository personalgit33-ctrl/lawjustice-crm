'use client';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from './Icon';
import { t } from '@/i18n';
import type { Channel, ConflictStatus, DeadlineState } from '@/lib/types';

export const CH: Record<string, [string, string]> = {
  wa: ['WhatsApp', 'var(--ch-whatsapp)'], g: ['Google', 'var(--ch-google)'], meta: ['Meta', 'var(--ch-meta)'], ph: ['Телефония', 'var(--ch-phone)'], manual: ['Вручную', 'var(--label-gray)'],
};
export function ChTag({ c }: { c?: Channel | '' | null }) {
  if (!c || !CH[c]) return null;
  return <span className="tag o"><i style={{ background: CH[c][1] }} />{CH[c][0]}</span>;
}
export function Ava({ name, initials, small = true, ai }: { name?: string; initials?: string; small?: boolean; ai?: boolean }) {
  const ini = initials || (name ? name.split(/\s+/).map((x) => x[0]).join('').slice(0, 2).toUpperCase() : '?');
  return <div className={`ava ${small ? 's' : ''} ${ai ? 'ai' : ''}`} title={name}>{ini}</div>;
}
export function CfTag({ s }: { s: ConflictStatus | string }) {
  if (s === 'hit') return <span className="tag r"><Icon name="alert" />{t('cf.hit')}</span>;
  if (s === 'ok') return <span className="tag g"><Icon name="shield" />{t('cf.ok')}</span>;
  if (s === 'cleared') return <span className="tag g"><Icon name="shield" />{t('cf.cleared')}</span>;
  if (s === 'refused') return <span className="tag r">{t('cf.refused')}</span>;
  return <span className="tag">{t('cf.none')}</span>;
}
export function DueTag({ s }: { s: DeadlineState | null | undefined }) {
  if (!s) return null;
  const cls = { late: 'r', today: 'a', week: 'b', later: '', done: 'g' }[s];
  return <span className={`tag ${cls}`}>{t('dl.' + s)}</span>;
}
export function Kpi({ label, value, sub, cls }: { label: string; value: ReactNode; sub?: ReactNode; cls?: string }) {
  return <div className="card kpi"><span>{label}</span><b>{value}</b><em className={cls || ''}>{sub}</em></div>;
}
export function Loading() { return <div className="state"><div className="spin" />{t('state.loading')}</div>; }
export function Empty({ text }: { text?: string }) { return <div className="state">{text || t('state.empty')}</div>; }
export function ErrorState({ error, retry }: { error: any; retry?: () => void }) {
  return <div className="state err"><div>{error?.status === 403 ? t('state.forbidden') : (error?.message || t('state.error'))}</div>
    {retry && <button className="btn ghost sm" style={{ marginTop: 10 }} onClick={retry}>{t('state.retry')}</button>}</div>;
}
export function Toggle({ on, onChange, disabled }: { on: boolean; onChange?: (v: boolean) => void; disabled?: boolean }) {
  return <div role="switch" aria-checked={on} className={`toggle ${on ? 'on' : ''}`} style={disabled ? { opacity: .5, cursor: 'not-allowed' } : undefined} onClick={() => !disabled && onChange && onChange(!on)} />;
}
export function Modal({ onClose, children, small }: { onClose: () => void; children: ReactNode; small?: boolean }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [onClose]);
  return <div className="modal" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={`mbox ${small ? 'sm' : ''}`}><button className="mclose" onClick={onClose} aria-label={t('common.close')}><Icon name="x" /></button>{children}</div>
  </div>;
}
export function Seg<T extends string>({ value, options, onChange }: { value: T; options: [T, ReactNode][]; onChange: (v: T) => void }) {
  return <div className="seg">{options.map(([k, l]) => <button key={k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>{l}</button>)}</div>;
}

/** Загрузка данных с состояниями loading / error. */
export function useLoad<T>(fn: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn); fnRef.current = fn;
  const seq = useRef(0);
  const reload = useCallback(async (silent = false) => {
    const my = ++seq.current;
    if (!silent) setLoading(true);
    try { const d = await fnRef.current(); if (my === seq.current) { setData(d); setError(null); } }
    catch (e) { if (my === seq.current) setError(e); }
    finally { if (my === seq.current) setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return { data, setData, error, loading, reload };
}

/** Обёртка: Loading / Error / контент */
export function View<T>({ s, children }: { s: { data: T | null; error: any; loading: boolean; reload: () => void }; children: (d: T) => ReactNode }) {
  if (s.loading && s.data == null) return <Loading />;
  if (s.error && s.data == null) return <ErrorState error={s.error} retry={() => s.reload()} />;
  if (s.data == null) return <Empty />;
  return <>{children(s.data)}</>;
}
