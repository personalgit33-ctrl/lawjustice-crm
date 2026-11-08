'use client';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { get } from '@/lib/api';
import type { Dictionaries, User } from '@/lib/types';

interface Counters { inbox: number; deadlines: number; conflicts: number }
interface Ctx {
  user: User;
  setUser: (u: User) => void;
  users: User[];
  userById: (id: number | null | undefined) => User | undefined;
  dict: Dictionaries;
  reloadDict: () => void;
  reloadUsers: () => void;
  counters: Counters;
  refreshCounters: () => void;
  sound: boolean;
  setSound: (v: boolean) => void;
}
const C = createContext<Ctx | null>(null);
export const useApp = () => { const c = useContext(C); if (!c) throw new Error('no app ctx'); return c; };

const emptyDict = { case_category: [], case_status: [], source: [], tag: [], refusal_reason: [], deadline_template: [], quick_reply: [] } as Dictionaries;

export function AppProvider({ user: u0, children }: { user: User; children: ReactNode }) {
  const [user, setUser] = useState(u0);
  const [users, setUsers] = useState<User[]>([]);
  const [dict, setDict] = useState<Dictionaries>(emptyDict);
  const [counters, setCounters] = useState<Counters>({ inbox: 0, deadlines: 0, conflicts: 0 });
  const [sound, setSoundS] = useState(true);
  useEffect(() => { try { setSoundS(localStorage.getItem('lj_sound') !== '0'); } catch {} }, []);
  const setSound = (v: boolean) => { setSoundS(v); try { localStorage.setItem('lj_sound', v ? '1' : '0'); } catch {} };

  const reloadUsers = useCallback(() => { get<User[]>('users/').then(setUsers).catch(() => {}); }, []);
  const reloadDict = useCallback(() => { get<Dictionaries>('dict/').then((d) => setDict({ ...emptyDict, ...d })).catch(() => {}); }, []);
  const refreshCounters = useCallback(async () => {
    const [cv, dl, cf] = await Promise.allSettled([
      get<{ unread: number }[]>('conversations/?filter=unread'),
      get<{ late: number }>('deadlines/counts/'),
      get<any[]>('conflicts/?status=pending'),
    ]);
    setCounters({
      inbox: cv.status === 'fulfilled' ? cv.value.reduce((a, c) => a + (c.unread ? 1 : 0), 0) : 0,
      deadlines: dl.status === 'fulfilled' ? dl.value.late || 0 : 0,
      conflicts: cf.status === 'fulfilled' ? cf.value.length : 0,
    });
  }, []);
  useEffect(() => { reloadUsers(); reloadDict(); refreshCounters(); const i = setInterval(refreshCounters, 60000); return () => clearInterval(i); }, [reloadUsers, reloadDict, refreshCounters]);

  const map = useMemo(() => new Map(users.map((x) => [x.id, x])), [users]);
  const userById = useCallback((id: number | null | undefined) => (id == null ? undefined : map.get(id)), [map]);
  return <C.Provider value={{ user, setUser, users, userById, dict, reloadDict, reloadUsers, counters, refreshCounters, sound, setSound }}>{children}</C.Provider>;
}

/** Короткий звуковой сигнал без файлов. */
export function beep() {
  try {
    const A = (window as any).AudioContext || (window as any).webkitAudioContext; if (!A) return;
    const ctx = new A(); const o = ctx.createOscillator(); const g = ctx.createGain();
    o.frequency.value = 880; g.gain.value = 0.05; o.connect(g); g.connect(ctx.destination); o.start();
    setTimeout(() => { o.frequency.value = 660; }, 120); setTimeout(() => { o.stop(); ctx.close(); }, 260);
  } catch {}
}
