'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from './Icon';
import { useApp, beep } from './AppContext';
import { toast, toastErr } from './toast';
import { Ava, Empty, Modal } from './ui';
import { TwoFA } from './TwoFA';
import { get, post, tokens } from '@/lib/api';
import { useEvents, stopEvents } from '@/lib/ws';
import { can, isManager, sectionOf, type Section } from '@/lib/access';
import { dt } from '@/lib/format';
import { t } from '@/i18n';
import type { Notification, IncomingCallEvent } from '@/lib/types';

type NavItem = [Section | 'sep', string, string, ('inbox' | 'deadlines' | 'conflicts')?, string?];
const NAV: NavItem[] = [
  ['dashboard', 'dash', 'nav.dashboard'], ['inbox', 'inbox', 'nav.inbox', 'inbox'], ['boards', 'boards', 'nav.boards'], ['calls', 'phone', 'nav.calls'],
  ['deadlines', 'clock', 'nav.deadlines', 'deadlines', 'r'], ['assistant', 'term', 'nav.assistant'],
  ['sep', '', 'nav.sep.work'], ['clients', 'users', 'nav.clients'], ['cases', 'case', 'nav.cases'], ['conflicts', 'shield', 'nav.conflicts', 'conflicts'],
  ['calendar', 'cal', 'nav.calendar'], ['finance', 'fin', 'nav.finance'],
  ['sep', '', 'nav.sep.manage'], ['reports', 'chart', 'nav.reports'], ['audit', 'log', 'nav.audit'], ['settings', 'set', 'nav.settings'],
];
const MNAV: [Section, string, string][] = [['dashboard', 'dash', 'nav.dashboard'], ['inbox', 'inbox', 'mnav.inbox'], ['boards', 'boards', 'nav.boards'], ['deadlines', 'clock', 'nav.deadlines'], ['calendar', 'cal', 'nav.calendar']];

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname() || '/';
  const router = useRouter();
  const { user, counters, refreshCounters, sound } = useApp();
  const sec = sectionOf(path);
  const [online, setOnline] = useState(true);
  const [call, setCall] = useState<IncomingCallEvent | null>(null);
  const [profile, setProfile] = useState(false);

  useEffect(() => {
    try { const sb = localStorage.getItem('lj_sidebar'); if (sb) document.documentElement.dataset.sidebar = sb; } catch {}
    try {
      const left = sessionStorage.getItem('lj_recovery_left');
      if (left !== null) { sessionStorage.removeItem('lj_recovery_left'); toast(`Вход по резервному коду. Осталось кодов: ${left}. Новые можно выпустить в профиле.`); }
    } catch {}
    const u = () => setOnline(navigator.onLine); u();
    window.addEventListener('online', u); window.addEventListener('offline', u);
    return () => { window.removeEventListener('online', u); window.removeEventListener('offline', u); };
  }, []);

  useEvents((e) => {
    if (e.type === 'call.incoming') { setCall(e.payload as IncomingCallEvent); if (sound) beep(); }
    if (e.type === 'message.new') { if (sound && e.payload?.message?.author === 'client') beep(); refreshCounters(); }
    if (e.type === 'notification') { toast(e.payload?.text || 'Новое уведомление'); if (sound) beep(); }
    if (e.type === 'conversation.updated') refreshCounters();
  }, [sound]);

  const title = sec ? t('title.' + sec) : '';
  const allowed = !sec || can(user.role, sec);
  const flush = sec === 'inbox';
  const cnt = (k?: 'inbox' | 'deadlines' | 'conflicts') => (k ? counters[k] : 0);

  const logout = () => { tokens.clear(); stopEvents(); router.replace('/login'); };

  return <div className="app">
    <aside className="side">
      <div className="side-in">
        <div className="brand"><div className="mark"><Icon name="scale" /></div><div className="bname"><b>{t('brand.name')}</b><small>{t('brand.sub')}</small></div></div>
        <nav className="nav">{NAV.filter(([k], i, arr) => {
          if (k !== 'sep') return can(user.role, k);
          // скрываем заголовок раздела, если под ним пусто
          for (let j = i + 1; j < arr.length && arr[j][0] !== 'sep'; j++) if (can(user.role, arr[j][0] as Section)) return true;
          return false;
        }).map(([k, ic, label, c, cl], i) => k === 'sep'
          ? <div key={'s' + i} className="sep"><span>{t(label)}</span></div>
          : <Link key={k} href={'/' + k} className={sec === k ? 'on' : ''} title={t(label)}><span className="nic"><Icon name={ic} />{cnt(c) ? <i className={`bdg ${cl || ''}`} /> : null}</span><span className="lb">{t(label)}</span>{cnt(c) ? <span className={`cnt ${cl || ''}`}>{cnt(c)}</span> : null}</Link>)}</nav>
        <div className="me">
          <div className="me-in" onClick={() => setProfile(true)} title="Профиль и безопасность">
            <div className="ava">{user.initials}</div>
            <div className="mtxt"><b>{user.full_name}</b><small>{user.role_label || t('role.' + user.role)}</small></div>
            <button onClick={(e) => { e.stopPropagation(); logout(); }} title={t('common.logout')}><Icon name="logout" /></button>
          </div>
        </div>
      </div>
    </aside>
    <main className="main">
      <Topbar title={title} onLogout={logout} />
      {!online && <div className="offline">{t('state.offline')}</div>}
      <div className={`content ${flush ? 'flush' : ''}`}>{allowed ? children : <Empty text={t('state.forbidden')} />}</div>
      <div className="mnav">{MNAV.filter(([k]) => can(user.role, k)).map(([k, ic, l]) => <Link key={k} href={'/' + k} className={sec === k ? 'on' : ''}><Icon name={ic} />{t(l)}</Link>)}</div>
    </main>
    {call && <CallPopup ev={call} onClose={() => setCall(null)} />}
    {profile && <Modal small onClose={() => setProfile(false)}><h2>{user.full_name}</h2><div className="kv"><span>Логин</span><div>{user.username}</div><span>Роль</span><div>{user.role_label}</div><span>Email</span><div>{user.email || '—'}</div><span>Телефон</span><div>{user.phone || '—'}</div></div><h3>Двухфакторный вход</h3><TwoFA /><div className="row" style={{ marginTop: 16 }}><button className="btn ghost sm" onClick={logout}><Icon name="logout" />{t('common.logout')}</button></div></Modal>}
  </div>;
}

function Topbar({ title, onLogout }: { title: string; onLogout: () => void }) {
  const { user, sound, setSound } = useApp();
  const router = useRouter();
  const [q, setQ] = useState('');
  const [res, setRes] = useState<any>(null);
  const [bell, setBell] = useState(false);
  const [notifs, setNotifs] = useState<Notification[]>([]);
  const boxRef = useRef<HTMLDivElement>(null);

  const loadN = () => get<Notification[]>('notifications/').then(setNotifs).catch(() => {});
  useEffect(() => { loadN(); const i = setInterval(loadN, 60000); return () => clearInterval(i); }, []);
  useEvents((e) => { if (e.type === 'notification') loadN(); });

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const h = setTimeout(() => get('search/?q=' + encodeURIComponent(q.trim())).then(setRes).catch(() => setRes(null)), 250);
    return () => clearTimeout(h);
  }, [q]);
  useEffect(() => {
    const c = (e: MouseEvent) => { if (boxRef.current && !boxRef.current.contains(e.target as Node)) setRes(null); };
    document.addEventListener('mousedown', c); return () => document.removeEventListener('mousedown', c);
  }, []);

  const unread = notifs.filter((n) => !n.is_read).length;
  const go = (href: string) => { setRes(null); setQ(''); router.push(href); };
  const simulate = async () => { try { await post('simulate/call/', { phone: '+996 555 12 34 56' }); } catch (e) { toastErr(e); } };

  const groups: [string, string, (x: any) => [string, string, string]][] = [
    ['clients', 'search.clients', (x) => [`/clients/${x.id}`, x.name, x.phone]],
    ['cases', 'search.cases', (x) => [`/cases/${x.id}`, `№ ${x.number} · ${x.title}`, x.client_name]],
    ['cards', 'search.cards', (x) => [`/boards?card=${x.id}${x.board ? '&board=' + x.board : ''}`, x.title, x.board_name || '']],
    ['conversations', 'search.conversations', (x) => [`/inbox?c=${x.id}`, x.client_name, x.last_message]],
  ];
  const total = res ? groups.reduce((a, [k]) => a + (res[k]?.length || 0), 0) : 0;

  return <div className="top">
    <div style={{ minWidth: 0 }}><div className="crumbs"><Link href="/dashboard">{t('brand.short')}</Link><Icon name="chev" /><span>{title}</span></div><h1>{title}</h1></div>
    <div className="search" ref={boxRef}><Icon name="search" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('search.placeholder')} onKeyDown={(e) => e.key === 'Escape' && setRes(null)} />
      {res && <div className="sres">{total === 0 ? <div className="state" style={{ padding: 16 }}>{t('search.nothing')}</div> :
        groups.map(([k, l, f]) => res[k]?.length ? <div key={k}><div className="sg">{t(l)}</div>{res[k].map((x: any) => { const [h, a, b] = f(x); return <a key={h} href={h} onClick={(e) => { e.preventDefault(); go(h); }}><div style={{ fontWeight: 500 }}>{a}</div>{b && <div className="muted small" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{b}</div>}</a>; })}</div> : null)}</div>}
    </div>
    {isManager(user.role) && <button className="ib" title="Симуляция входящего звонка" onClick={simulate}><Icon name="phone" /></button>}
    <button className="ib" title={t('notif.sound')} onClick={() => setSound(!sound)}><Icon name={sound ? 'vol' : 'mute'} /></button>
    <button className={`ib ${bell ? 'on' : ''}`} onClick={() => setBell(!bell)} title={t('notif.title')}><Icon name="bell" />{unread > 0 && <i className="dot">{unread > 9 ? '9+' : unread}</i>}</button>
    {bell && <div className="pop">
      <div className="ph">{t('notif.title')}<button className="btn link small" style={{ marginLeft: 'auto' }} onClick={async () => { try { await post('notifications/read-all/'); loadN(); } catch (e) { toastErr(e); } }}>{t('notif.readAll')}</button></div>
      <div className="pl">{notifs.length === 0 ? <div className="state">{t('notif.empty')}</div> : notifs.map((n) => <div key={n.id} className={`pi ${n.is_read ? '' : 'un'}`} onClick={() => { setBell(false); if (n.link) router.push(n.link); }}>
        <div>{n.text}</div><div className="muted small">{dt(n.created_at)}</div></div>)}</div>
    </div>}
  </div>;
}

function CallPopup({ ev, onClose }: { ev: IncomingCallEvent; onClose: () => void }) {
  const router = useRouter();
  const act = async (a: 'answer' | 'to-ai') => {
    try { await post(`calls/${ev.call_id}/${a}/`); toast(a === 'answer' ? 'Разговор идёт · запись и расшифровка включены' : 'Звонок передан ассистенту'); } catch (e) { toastErr(e); }
    onClose();
  };
  const c = ev.client;
  return <div className="callpop">
    <div className="hd"><div className="row"><i className="ring" /><b style={{ fontWeight: 600 }}>Входящий звонок</b></div><span style={{ opacity: .75, fontSize: 12 }}>{ev.phone}</span></div>
    <div style={{ padding: 14 }}>
      <div style={{ fontSize: 17, fontWeight: 600 }}>{c ? c.name : 'Неизвестный номер'}</div>
      <div className="muted small" style={{ margin: '2px 0 10px' }}>{c ? `Клиент${c.responsible_name ? ' · ответственный ' + c.responsible_name : ''}` : 'Клиента с таким номером нет в базе'}</div>
      <div className="small" style={{ borderTop: '1px solid var(--border)', paddingTop: 8, lineHeight: 1.7 }}>
        {ev.open_cards?.length ? <>Открытые карточки: {ev.open_cards.map((x) => `«${x}»`).join(', ')}<br /></> : null}
        {ev.last_contact && <>Последний контакт: {ev.last_contact}<br /></>}
        {ev.nearest && <>Ближайшее: {ev.nearest}</>}
        {!c && <button className="btn ghost sm" style={{ marginTop: 4 }} onClick={() => { onClose(); router.push(`/clients?new=1&phone=${encodeURIComponent(ev.phone)}`); }}><Icon name="plus" />Создать клиента</button>}
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn grn" onClick={() => act('answer')}><Icon name="phone" />Ответить</button>
        <button className="btn ghost" onClick={() => act('to-ai')}>Передать ассистенту</button>
        <button className="btn red" style={{ marginLeft: 'auto' }} onClick={onClose} aria-label="Скрыть"><Icon name="x" /></button>
      </div>
      {c && <button className="btn link small" style={{ marginTop: 8 }} onClick={() => { onClose(); router.push(`/clients/${c.id}`); }}>Открыть карточку клиента</button>}
    </div>
  </div>;
}

export { Ava };
