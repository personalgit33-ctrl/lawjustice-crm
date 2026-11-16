'use client';
import { useEffect, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { login } from '@/lib/api';
import { Icon } from '@/components/Icon';
import { t } from '@/i18n';

export default function LoginPage() {
  const router = useRouter();
  const [u, setU] = useState(''); const [p, setP] = useState(''); const [otp, setOtp] = useState('');
  const [needOtp, setNeedOtp] = useState(false); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [idle, setIdle] = useState(false);
  useEffect(() => { setIdle(!!new URLSearchParams(location.search).get('idle')); }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setBusy(true);
    try {
      await login(u.trim(), p, needOtp ? otp.trim() : undefined);
      const next = new URLSearchParams(location.search).get('next');
      router.replace(next && next.startsWith('/') && next !== '/login' ? next : '/dashboard');
    } catch (e: any) {
      if (e?.data?.otp_required) { setNeedOtp(true); setErr(needOtp ? (e.message || t('login.error')) : t('login.otpRequired')); }
      else setErr(e?.status === 0 ? e.message : (e?.message || t('login.error')));
    } finally { setBusy(false); }
  };
  return <div className="login"><form className="card" onSubmit={submit}>
    <div className="logo"><div className="mark"><Icon name="scale" /></div><div><b style={{ letterSpacing: '.12em', fontSize: 13 }}>{t('brand.name')}</b><div className="muted small">CRM · {t('brand.sub')}</div></div></div>
    <h3 style={{ fontSize: 17 }}>{t('login.title')}</h3>
    {idle && <div className="note" style={{ marginBottom: 12 }}>Сеанс завершён после бездействия. Войдите снова.</div>}
    <div className="lbl">{t('login.username')}</div><input className="fld" value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" required />
    <div className="lbl" style={{ marginTop: 10 }}>{t('login.password')}</div><input className="fld" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required />
    {needOtp && <><div className="lbl" style={{ marginTop: 10 }}>{t('login.otp')}</div><input className="fld" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} autoFocus autoComplete="one-time-code" /></>}
    {err && <div className="note r" style={{ marginTop: 12 }}>{err}</div>}
    <button className="btn w100" style={{ marginTop: 16, padding: '9px 13px' }} disabled={busy}>{busy ? t('state.loading') : t('login.submit')}</button>
  </form></div>;
}
