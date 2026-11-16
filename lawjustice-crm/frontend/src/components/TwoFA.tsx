'use client';
import { useState } from 'react';
import { post } from '@/lib/api';
import { useApp } from './AppContext';
import { Icon } from './Icon';
import { OtpInput, QrSetup, RecoveryCodes } from './auth';
import { toast, toastErr } from './toast';
import type { TwoFASetup, User } from '@/lib/types';

/** Двухфакторный вход в профиле: включить, перевыпустить резервные коды, отключить (если роль позволяет). */
export function TwoFA() {
  const { user, setUser } = useApp();
  const [setup, setSetup] = useState<TwoFASetup | null>(null);
  const [mode, setMode] = useState<'' | 'codes' | 'disable'>('');
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { setCode(''); toastErr(e); } finally { setBusy(false); } };

  if (codes) return <div><RecoveryCodes codes={codes} /><button className="btn sm" style={{ marginTop: 12 }} onClick={() => setCodes(null)}>Готово</button></div>;

  if (user.has_2fa) return <div>
    <div className="note"><Icon name="shield" /><div>Двухфакторный вход включён. Осталось резервных кодов: <b>{user.recovery_left}</b>{user.recovery_left <= 2 && ' — выпустите новые.'}</div></div>
    {!mode && <div className="row wrap" style={{ marginTop: 12 }}>
      <button className="btn ghost sm" onClick={() => { setMode('codes'); setCode(''); }}><Icon name="key" />Новые резервные коды</button>
      {!user.twofa_required && <button className="btn ghost sm" onClick={() => { setMode('disable'); setCode(''); }}><Icon name="x" />Отключить</button>}
    </div>}
    {mode && <div style={{ marginTop: 14 }}>
      <div className="small" style={{ marginBottom: 8 }}>{mode === 'codes' ? 'Введите код из приложения — старые резервные коды перестанут действовать.' : 'Введите код из приложения, чтобы отключить двухфакторный вход.'}</div>
      <OtpInput value={code} onChange={setCode} disabled={busy} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className={`btn sm ${mode === 'disable' ? 'red' : ''}`} disabled={busy || !/^\d{6}$/.test(code)} onClick={() => run(async () => {
          if (mode === 'codes') { const r = await post<{ recovery_codes: string[] }>('auth/2fa/recovery-codes/', { code }); setCodes(r.recovery_codes); setUser({ ...user, recovery_left: r.recovery_codes.length }); }
          else { setUser(await post<User>('auth/2fa/disable/', { code })); toast('Двухфакторный вход отключён'); }
          setMode(''); setCode('');
        })}>{mode === 'codes' ? 'Выпустить коды' : 'Отключить'}</button>
        <button className="btn ghost sm" onClick={() => setMode('')}>Отмена</button>
      </div>
    </div>}
  </div>;

  return <div>
    {user.twofa_required && <div className="note w" style={{ marginBottom: 12 }}><Icon name="alert" /><div>Для роли «{user.role_label}» двухфакторный вход обязателен (ТЗ 12.7). Без него при следующем входе система попросит настроить его.</div></div>}
    {!setup ? <button className="btn sm" disabled={busy} onClick={() => run(async () => { setSetup(await post<TwoFASetup>('auth/2fa/setup/')); setCode(''); })}><Icon name="lock" />Включить двухфакторный вход</button> : <>
      <QrSetup setup={setup} />
      <div className="lbl" style={{ margin: '12px 0 8px' }}>Код из приложения</div>
      <OtpInput value={code} onChange={setCode} disabled={busy} autoFocus={false} />
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn sm" disabled={busy || !/^\d{6}$/.test(code)} onClick={() => run(async () => {
          const r = await post<User & { recovery_codes: string[] }>('auth/2fa/enable/', { code });
          const { recovery_codes, ...u } = r; setUser(u as User); setCodes(recovery_codes); setSetup(null); toast('Двухфакторный вход включён');
        })}>Подтвердить</button>
        <button className="btn ghost sm" onClick={() => setSetup(null)}>Отмена</button>
      </div></>}
  </div>;
}
