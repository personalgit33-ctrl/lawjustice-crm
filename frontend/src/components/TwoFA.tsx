'use client';
import { useState } from 'react';
import { post } from '@/lib/api';
import { useApp } from './AppContext';
import { Icon } from './Icon';
import { toast, toastErr } from './toast';
import type { User } from '@/lib/types';

export function TwoFA() {
  const { user, setUser } = useApp();
  const [setup, setSetup] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [otp, setOtp] = useState('');
  if (user.has_2fa) return <div className="note"><Icon name="shield" /><div>Двухфакторная аутентификация включена для вашей учётной записи.</div></div>;
  return <div>
    {(user.role === 'admin' || user.role === 'manager') && <div className="note w" style={{ marginBottom: 10 }}><Icon name="alert" /><div>Для роли «{user.role_label}» двухфакторный вход обязателен (ТЗ 12.7).</div></div>}
    {!setup ? <button className="btn sm" onClick={async () => { try { setSetup(await post('auth/2fa/setup/')); } catch (e) { toastErr(e); } }}><Icon name="lock" />Включить 2FA</button> : <>
      <div className="small" style={{ marginBottom: 8 }}>Добавьте ключ в приложение-аутентификатор (Google Authenticator, Яндекс Ключ и др.):</div>
      <div className="fld" style={{ fontFamily: 'ui-monospace,monospace', wordBreak: 'break-all', marginBottom: 6 }}>{setup.secret}</div>
      <a className="lnk small" href={setup.otpauth_url}>Открыть в приложении на этом устройстве</a>
      <div className="row" style={{ marginTop: 10 }}><input className="fld" style={{ width: 140 }} inputMode="numeric" maxLength={6} placeholder="Код" value={otp} onChange={(e) => setOtp(e.target.value)} />
        <button className="btn sm" onClick={async () => { try { setUser(await post<User>('auth/2fa/enable/', { otp })); toast('2FA включена'); } catch (e) { toastErr(e); } }}>Подтвердить</button></div></>}
  </div>;
}
