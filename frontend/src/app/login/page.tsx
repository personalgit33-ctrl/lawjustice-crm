'use client';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { enrollFinish, enrollStart, login, loginVerify } from '@/lib/api';
import { Icon } from '@/components/Icon';
import { OtpInput, PasswordInput, QrSetup, RecoveryCodes } from '@/components/auth';
import { t } from '@/i18n';
import type { TwoFASetup } from '@/lib/types';

type Stage = 'password' | 'otp' | 'setup' | 'codes';

export default function LoginPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>('password');
  const [u, setU] = useState(''); const [p, setP] = useState('');
  const [mfa, setMfa] = useState(''); const [code, setCode] = useState(''); const [useRecovery, setUseRecovery] = useState(false);
  const [setup, setSetup] = useState<TwoFASetup | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [err, setErr] = useState(''); const [info, setInfo] = useState(''); const [busy, setBusy] = useState(false);

  // Форма рисуется только в браузере: расширения (менеджеры паролей, антивирусы, автозаполнение)
  // меняют форму входа до гидратации, и серверная разметка перестаёт совпадать с клиентской.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    if (new URLSearchParams(location.search).get('idle')) setInfo('Сеанс завершён после бездействия. Войдите снова.');
  }, []);

  const finish = () => {
    const next = new URLSearchParams(location.search).get('next');
    router.replace(next && next.startsWith('/') && next !== '/login' ? next : '/dashboard');
  };
  const restart = (msg = '') => { setStage('password'); setMfa(''); setCode(''); setSetup(null); setUseRecovery(false); setErr(msg); };
  const failed = (e: any) => {
    if (e?.data?.restart) return restart(e.message);
    setErr(e?.status === 0 ? e.message : (e?.message || t('login.error')));
  };

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault(); setErr(''); setInfo(''); setBusy(true);
    try { await login(u.trim(), p); finish(); }
    catch (e: any) {
      if (e?.data?.otp_required) { setMfa(e.data.mfa_token); setCode(''); setStage('otp'); }
      else if (e?.data?.setup_required) {
        setMfa(e.data.mfa_token); setInfo(e.message);
        try { setSetup(await enrollStart(e.data.mfa_token)); setCode(''); setStage('setup'); } catch (x) { failed(x); }
      } else failed(e);
    } finally { setBusy(false); }
  };

  const submitCode = async (c = code) => {
    const v = c.trim(); if (!v || busy) return;
    setErr(''); setBusy(true);
    try {
      const r = await loginVerify(mfa, v);
      if (r.recovery_left !== undefined) sessionStorage.setItem('lj_recovery_left', String(r.recovery_left));
      finish();
    } catch (e) { setCode(''); failed(e); } finally { setBusy(false); }
  };

  const submitSetup = async (c = code) => {
    if (!/^\d{6}$/.test(c) || busy) return;
    setErr(''); setBusy(true);
    try { const r = await enrollFinish(mfa, c); setCodes(r.recovery_codes || []); setStage('codes'); }
    catch (e) { setCode(''); failed(e); } finally { setBusy(false); }
  };

  if (!mounted) return <div className="auth" suppressHydrationWarning />;

  return <div className="auth">
    <div className="auth-deco l" aria-hidden="true" /><div className="auth-deco r" aria-hidden="true" />
    <div className={`auth-card ${stage === 'setup' || stage === 'codes' ? 'wide' : ''}`}>
      {stage === 'password' && <form onSubmit={submitPassword}>
        <Brand title={t('login.title')} />
        {info && <div className="note" style={{ marginBottom: 14 }}><Icon name="info" /><div>{info}</div></div>}
        <div className="afield"><input className="ain" value={u} onChange={(e) => setU(e.target.value)} placeholder={t('login.username')} autoFocus autoComplete="username" required /></div>
        <div className="afield"><PasswordInput className="ain" value={p} onChange={(e) => setP(e.target.value)} placeholder={t('login.password')} autoComplete="current-password" required /></div>
        {err && <div className="aerr">{err}</div>}
        <button className="abtn" disabled={busy || !u.trim() || !p}>{busy ? t('state.loading') : t('login.submit')}</button>
        <Foot />
      </form>}

      {stage === 'otp' && <form onSubmit={(e) => { e.preventDefault(); submitCode(); }}>
        <Back onClick={() => restart()} />
        <Brand title="Подтверждение входа" icon="phoneApp" />
        <p className="asub">{useRecovery ? 'Введите один из резервных кодов, которые вы сохранили при настройке.' : 'Откройте приложение-аутентификатор и введите 6-значный код для Law & Justice CRM.'}</p>
        {useRecovery
          ? <div className="afield"><input className="ain mono" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="XXXX-XXXX" maxLength={9} autoFocus autoComplete="off" /></div>
          : <OtpInput value={code} onChange={setCode} onComplete={(v) => submitCode(v)} disabled={busy} />}
        {err && <div className="aerr">{err}</div>}
        <button className="abtn" disabled={busy || (useRecovery ? code.replace(/\W/g, '').length < 8 : !/^\d{6}$/.test(code))}>{busy ? 'Проверяем…' : 'Подтвердить'}</button>
        <button type="button" className="alink" onClick={() => { setUseRecovery(!useRecovery); setCode(''); setErr(''); }}>
          {useRecovery ? 'Ввести код из приложения' : 'Нет доступа к телефону? Войти по резервному коду'}</button>
        <Foot />
      </form>}

      {stage === 'setup' && setup && <form onSubmit={(e) => { e.preventDefault(); submitSetup(); }}>
        <Back onClick={() => restart()} />
        <Brand title="Настройка двухфакторного входа" icon="shield" />
        {info && <p className="asub">{info}</p>}
        <QrSetup setup={setup} />
        <div className="lbl" style={{ textAlign: 'center', margin: '14px 0 8px' }}>Код из приложения</div>
        <OtpInput value={code} onChange={setCode} onComplete={(v) => submitSetup(v)} disabled={busy} autoFocus={false} />
        {err && <div className="aerr">{err}</div>}
        <button className="abtn" disabled={busy || !/^\d{6}$/.test(code)}>{busy ? 'Проверяем…' : 'Включить и войти'}</button>
      </form>}

      {stage === 'codes' && <div>
        <Brand title="Двухфакторный вход включён" icon="ok" />
        <RecoveryCodes codes={codes} />
        <button className="abtn" onClick={finish}>Я сохранил коды, продолжить</button>
      </div>}
    </div>
  </div>;
}

function Brand({ title, icon = 'scale' }: { title: string; icon?: string }) {
  return <div className="abrand">
    <div className="amark"><Icon name={icon} /></div>
    {icon === 'scale' && <div className="aname">{t('brand.name')}<small>CRM · {t('brand.sub')}</small></div>}
    <h1>{title}</h1>
  </div>;
}
function Back({ onClick }: { onClick: () => void }) {
  return <button type="button" className="aback" onClick={onClick} aria-label="Назад"><Icon name="left" /></button>;
}
function Foot(): ReactNode {
  return <div className="afoot">Law & Justice CRM © {new Date().getFullYear()}</div>;
}
