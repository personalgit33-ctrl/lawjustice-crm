'use client';
import { useEffect, useRef, useState, type InputHTMLAttributes } from 'react';
import { Icon } from './Icon';
import { toast } from './toast';
import type { TwoFASetup } from '@/lib/types';

/** Поле пароля с «глазком»: показать / скрыть введённый пароль. */
export function PasswordInput({ className = 'fld', ...p }: InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  return <div className="pw">
    <input {...p} className={className} type={show ? 'text' : 'password'} />
    <button type="button" className="pw-eye" onClick={() => setShow(!show)} aria-label={show ? 'Скрыть пароль' : 'Показать пароль'} title={show ? 'Скрыть пароль' : 'Показать пароль'} tabIndex={-1}>
      <Icon name={show ? 'eyeOff' : 'eye'} />
    </button>
  </div>;
}

/** Ввод 6-значного кода: ячейки, автопереход, вставка из буфера, Backspace. */
export function OtpInput({ value, onChange, onComplete, disabled, autoFocus = true }: { value: string; onChange: (v: string) => void; onComplete?: (v: string) => void; disabled?: boolean; autoFocus?: boolean }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  useEffect(() => { if (autoFocus) refs.current[0]?.focus(); }, [autoFocus]);
  // после неверного кода поле очищается — возвращаем курсор в первую ячейку
  useEffect(() => { if (value === '' && !disabled && document.activeElement?.closest('.otp')) refs.current[0]?.focus(); }, [value, disabled]);
  // пустая ячейка внутри строки хранится как пробел, чтобы цифры не сдвигались
  const digits = Array.from({ length: 6 }, (_, i) => (value[i] || '').trim());
  const setAt = (i: number, ch: string) => {
    const arr = digits.slice(); arr[i] = ch;
    const v = arr.map((c) => c || ' ').join('').trimEnd();
    onChange(v);
    if (/^\d{6}$/.test(v)) onComplete?.(v);
  };
  return <div className="otp" onPaste={(e) => {
    const t = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (!t) return;
    e.preventDefault(); onChange(t); refs.current[Math.min(t.length, 5)]?.focus();
    if (t.length === 6) onComplete?.(t);
  }}>
    {digits.map((d, i) => <input key={i} ref={(el) => { refs.current[i] = el; }} value={d} disabled={disabled} inputMode="numeric" autoComplete={i === 0 ? 'one-time-code' : 'off'} maxLength={1} aria-label={`Цифра ${i + 1}`}
      onChange={(e) => { const ch = e.target.value.replace(/\D/g, '').slice(-1); if (!ch) return; setAt(i, ch); if (i < 5) refs.current[i + 1]?.focus(); }}
      onKeyDown={(e) => {
        if (e.key === 'Backspace') { e.preventDefault(); if (d) setAt(i, ''); else if (i > 0) { refs.current[i - 1]?.focus(); setAt(i - 1, ''); } }
        if (e.key === 'ArrowLeft' && i > 0) refs.current[i - 1]?.focus();
        if (e.key === 'ArrowRight' && i < 5) refs.current[i + 1]?.focus();
      }}
      onFocus={(e) => e.target.select()} />)}
  </div>;
}

/** Шаги настройки приложения-аутентификатора: QR, ключ вручную. */
export function QrSetup({ setup }: { setup: TwoFASetup }) {
  const [manual, setManual] = useState(false);
  const secret = setup.secret.replace(/(.{4})/g, '$1 ').trim();
  return <div className="qrsetup">
    <ol className="steps2">
      <li>Установите на телефон <b>Google Authenticator</b>, <b>Microsoft Authenticator</b> или <b>Яндекс Ключ</b>.</li>
      <li>В приложении нажмите «+» и отсканируйте QR-код.</li>
      <li>Введите 6-значный код, который покажет приложение.</li>
    </ol>
    <div className="qrbox">
      <img src={setup.qr_svg} alt="QR-код для приложения-аутентификатора" width={176} height={176} />
    </div>
    {!manual ? <button type="button" className="btn link small" onClick={() => setManual(true)}>Не получается отсканировать? Ввести ключ вручную</button> :
      <div className="secret"><span>{secret}</span><button type="button" className="ib" title="Скопировать ключ" onClick={() => { navigator.clipboard?.writeText(setup.secret).then(() => toast('Ключ скопирован'), () => {}); }}><Icon name="copy" /></button></div>}
    <a className="btn link small mob-only" href={setup.otpauth_url}>Открыть в приложении на этом телефоне</a>
  </div>;
}

/** Резервные коды: показываются один раз, можно скопировать или скачать. */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  const text = `Law & Justice CRM — резервные коды двухфакторного входа\nКаждый код одноразовый. Храните в надёжном месте.\n\n${codes.join('\n')}\n`;
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = 'lawjustice-recovery-codes.txt'; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };
  return <div>
    <div className="note w" style={{ marginBottom: 12 }}><Icon name="key" /><div>Сохраните эти коды. Если телефон потеряется, по одному коду можно будет войти вместо кода из приложения. <b>Повторно коды не показываются.</b></div></div>
    <div className="codes">{codes.map((c) => <code key={c}>{c}</code>)}</div>
    <div className="row" style={{ marginTop: 12 }}>
      <button type="button" className="btn ghost sm" onClick={() => navigator.clipboard?.writeText(codes.join('\n')).then(() => toast('Коды скопированы'), () => {})}><Icon name="copy" />Скопировать</button>
      <button type="button" className="btn ghost sm" onClick={download}><Icon name="dl" />Скачать .txt</button>
    </div>
  </div>;
}
