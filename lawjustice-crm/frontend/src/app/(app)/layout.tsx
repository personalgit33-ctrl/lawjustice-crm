'use client';
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { me, setOnAuthLost, tokens } from '@/lib/api';
import { startEvents } from '@/lib/ws';
import { AppProvider } from '@/components/AppContext';
import { Shell } from '@/components/Shell';
import { Loading, ErrorState } from '@/components/ui';
import type { User } from '@/lib/types';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [err, setErr] = useState<any>(null);
  useEffect(() => {
    setOnAuthLost(() => router.replace('/login?next=' + encodeURIComponent(location.pathname)));
    if (!tokens.access) { router.replace('/login?next=' + encodeURIComponent(path || '/dashboard')); return; }
    me().then((u) => { setUser(u); startEvents(); }).catch((e) => { if (e.status === 401) router.replace('/login'); else setErr(e); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Автовыход после бездействия (ТЗ 12.7)
  useEffect(() => {
    if (!user) return;
    let last = Date.now();
    const bump = () => { last = Date.now(); };
    ['mousemove', 'keydown', 'click', 'touchstart'].forEach((e) => window.addEventListener(e, bump, { passive: true }));
    const i = setInterval(() => { if (Date.now() - last > 30 * 60 * 1000) { tokens.clear(); router.replace('/login?idle=1'); } }, 30000);
    return () => { clearInterval(i); ['mousemove', 'keydown', 'click', 'touchstart'].forEach((e) => window.removeEventListener(e, bump)); };
  }, [user, router]);
  if (err) return <ErrorState error={err} retry={() => location.reload()} />;
  if (!user) return <Loading />;
  return <AppProvider user={user}><Shell>{children}</Shell></AppProvider>;
}
