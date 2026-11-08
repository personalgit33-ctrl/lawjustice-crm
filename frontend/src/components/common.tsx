'use client';
import { useApp } from './AppContext';
import { Ava } from './ui';
import type { User } from '@/lib/types';

export function Resp({ id, full }: { id: number | null | undefined; full?: boolean }) {
  const { userById } = useApp(); const u = userById(id);
  if (!u) return <span className="muted">—</span>;
  return <div className="row"><Ava initials={u.initials} name={u.full_name} />{full ? u.full_name : u.full_name.split(' ')[0]}</div>;
}

export function UserSelect({ value, onChange, filter, empty = '—', className = 'fld' }: { value: number | null | undefined; onChange: (v: number | null) => void; filter?: (u: User) => boolean; empty?: string; className?: string }) {
  const { users } = useApp();
  const list = users.filter((u) => u.is_active && u.role !== 'ai' && (!filter || filter(u)));
  return <select className={className} value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
    <option value="">{empty}</option>{list.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
  </select>;
}

/** Выбор файла: скрытый input */
export function pickFiles(multiple = true): Promise<File[]> {
  return new Promise((res) => {
    const i = document.createElement('input'); i.type = 'file'; i.multiple = multiple;
    i.onchange = () => res(Array.from(i.files || [])); i.click();
  });
}
