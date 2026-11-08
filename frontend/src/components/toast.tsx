'use client';
import { useEffect, useState } from 'react';

type T = { id: number; text: string; err?: boolean };
let push: ((t: T) => void) | null = null;
let seq = 1;
export function toast(text: string, err = false) { push ? push({ id: seq++, text, err }) : console.log(text); }
export function toastErr(e: unknown) { toast((e as any)?.message || 'Ошибка', true); }

export function Toasts() {
  const [items, set] = useState<T[]>([]);
  useEffect(() => {
    push = (t) => { set((a) => [...a.slice(-3), t]); setTimeout(() => set((a) => a.filter((x) => x.id !== t.id)), t.err ? 4200 : 2800); };
    return () => { push = null; };
  }, []);
  return <div className="toasts">{items.map((t) => <div key={t.id} className={`toast ${t.err ? 'r' : ''}`}>{t.text}</div>)}</div>;
}
