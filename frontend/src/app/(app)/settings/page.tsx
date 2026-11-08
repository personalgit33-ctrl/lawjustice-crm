'use client';
import { useEffect, useState } from 'react';
import { del, download, get, patch, post } from '@/lib/api';
import { useApp } from '@/components/AppContext';
import { Icon } from '@/components/Icon';
import { Empty, Modal, Toggle, View, useLoad } from '@/components/ui';
import { UserSelect } from '@/components/common';
import { TwoFA } from '@/components/TwoFA';
import { PasswordInput } from '@/components/auth';
import { toast, toastErr } from '@/components/toast';
import { dt } from '@/lib/format';
import { t } from '@/i18n';
import type { AppSettings, DictKind, Role, User } from '@/lib/types';

type Tab = 'main' | 'security' | 'users' | 'dict' | 'me';
export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('main');
  const s = useLoad(() => get<AppSettings>('settings/'));
  const save = async (body: any) => { try { s.setData(await patch<AppSettings>('settings/', body)); toast('Настройки сохранены'); } catch (e) { toastErr(e); s.reload(true); } };
  return <>
    <div className="tabs">{([['main', 'Каналы и ассистент'], ['security', 'Безопасность и хранение'], ['users', 'Сотрудники и роли'], ['dict', 'Справочники'], ['me', 'Мой вход (2FA)']] as const).map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
    {tab === 'users' ? <Users /> : tab === 'dict' ? <Dicts /> : tab === 'me' ? <div className="card" style={{ maxWidth: 520 }}><h3>Двухфакторная аутентификация</h3><TwoFA /></div> :
      <View s={s}>{(st) => tab === 'main' ? <Main st={st} save={save} /> : <Security st={st} save={save} />}</View>}
  </>;
}

function Main({ st, save }: { st: AppSettings; save: (b: any) => void }) {
  const [kb, setKb] = useState(st.knowledge_base);
  useEffect(() => setKb(st.knowledge_base), [st.knowledge_base]);
  const ai = st.ai;
  const rules: [keyof AppSettings['ai'], string, string][] = [['chat_247', 'Отвечает в чатах 24/7', ''], ['calls_after_hours', 'Принимает звонки вне рабочего времени и при занятости', ''], ['draft_mode_wa', 'Режим «Черновик» для WhatsApp', 'Ответ отправляет сотрудник — на период запуска'], ['disclose_ai', 'Сообщает клиенту, что он — виртуальный ассистент, и о записи разговора', ''], ['masking', 'Маскирование ПИН, паспортных данных и счетов', 'перед передачей текста в модель'], ['skip_confidential', 'Не обрабатывает конфиденциальные дела', ''], ['no_legal_advice', 'Не даёт юридических оценок и прогнозов', 'ответ по шаблону и передача сотруднику']];
  return <div className="grid g2">
    <div className="card"><h3>Каналы и интеграции</h3>{Object.entries(st.integrations).map(([k, v]) => <div key={k} className="int"><div className="ic">{k.slice(0, 2).toUpperCase()}</div><div style={{ flex: 1 }}><b style={{ fontWeight: 500 }}>{v.label}</b><div className="muted small">{v.info}{!v.configured && <> · <span style={{ color: 'var(--warning)' }}>ключи не заданы</span></>}</div></div>
      <Toggle on={v.enabled} onChange={(x) => save({ integrations: { [k]: { enabled: x } } })} /></div>)}</div>
    <div className="card"><h3>Ассистент: правила</h3>{rules.map(([k, l, sub]) => <div key={k} className="set"><div>{l}{sub && <small>{sub}</small>}</div><Toggle on={!!ai[k]} onChange={(x) => save({ ai: { [k]: x } })} /></div>)}
      <div className="set"><div>Лимит расходов API<small>израсходовано {ai.spent_usd.toFixed(2)} $ · уведомление при 80 %</small></div><div className="row"><input className="fld" type="number" defaultValue={ai.monthly_limit_usd} onBlur={(e) => Number(e.target.value) !== ai.monthly_limit_usd && save({ ai: { monthly_limit_usd: Number(e.target.value) } })} /> $</div></div></div>
    <div className="card"><h3>База знаний ассистента</h3><div className="muted small" style={{ marginBottom: 8 }}>Описание компании, услуги, стоимость консультаций, частые вопросы, сценарии квалификации, правила передачи сотруднику, тон общения. Меняется без участия разработчика.</div>
      <textarea className="fld" style={{ height: 220 }} value={kb} onChange={(e) => setKb(e.target.value)} />
      <button className="btn sm" style={{ marginTop: 8 }} disabled={kb === st.knowledge_base} onClick={() => save({ knowledge_base: kb })}>{t('common.save')}</button></div>
    <div className="card"><h3>Рабочее время и напоминания</h3>
      <div className="set"><div>Рабочее время<small>вне его звонки и чаты принимает ассистент</small></div><div className="row"><input className="fld" type="time" defaultValue={st.work_hours.start} onBlur={(e) => save({ work_hours: { ...st.work_hours, start: e.target.value } })} />—<input className="fld" type="time" defaultValue={st.work_hours.end} onBlur={(e) => save({ work_hours: { ...st.work_hours, end: e.target.value } })} /></div></div>
      <div className="set"><div>Напоминания о сроках<small>за сколько дней, через запятую</small></div><input className="fld" defaultValue={st.reminders_days.join(', ')} onBlur={(e) => save({ reminders_days: e.target.value.split(',').map((x) => Number(x.trim())).filter((x) => !isNaN(x)) })} /></div>
      <div className="set"><div>Синее боковое меню<small>по умолчанию белое (ТЗ 3.6); синее — как в первом прототипе, на этом устройстве</small></div><Toggle on={typeof document !== 'undefined' && document.documentElement.dataset.sidebar === 'brand'} onChange={(x) => { document.documentElement.dataset.sidebar = x ? 'brand' : 'light'; try { localStorage.setItem('lj_sidebar', x ? 'brand' : 'light'); } catch {} }} /></div>
    </div>
  </div>;
}

function Security({ st, save }: { st: AppSettings; save: (b: any) => void }) {
  const sec = st.security;
  const num = (k: keyof AppSettings['security'], label: string, sub: string, unit: string) => <div className="set"><div>{label}<small>{sub}</small></div><div className="row"><input className="fld" type="number" defaultValue={Number(sec[k])} onBlur={(e) => Number(e.target.value) !== sec[k] && save({ security: { [k]: Number(e.target.value) } })} /><span className="small muted">{unit}</span></div></div>;
  const exp = async () => { try { toast('Готовим выгрузку…'); await download('export/all/', 'lawjustice-export.zip'); toast('Полная выгрузка данных — записана в журнал'); } catch (e) { toastErr(e); } };
  return <div className="grid g2">
    <div className="card"><h3>Доступ</h3>
      <div className="set"><div>Двухфакторный вход<small>администратор и руководитель</small></div><Toggle on={sec.require_2fa_admin} onChange={(x) => save({ security: { require_2fa_admin: x } })} /></div>
      <div className="set"><div>Экспорт базы только администратором<small>каждая выгрузка — в журнале</small></div><Toggle on={sec.export_admin_only} onChange={(x) => save({ security: { export_admin_only: x } })} /></div>
      <div className="set"><div>Журнал просмотров карточек<small>клиенты и конфиденциальные дела</small></div><Toggle on={sec.view_log} onChange={(x) => save({ security: { view_log: x } })} /></div>
      {num('idle_logout_min', 'Автовыход после бездействия', 'для всех ролей', 'мин')}
    </div>
    <div className="card"><h3>Хранение</h3>
      {num('recordings_retention_months', 'Срок хранения записей звонков', 'затем автоудаление с отметкой в журнале', 'мес.')}
      {num('archive_years', 'Архив закрытых дел', 'срок хранения', 'лет')}
      {num('stale_days', 'Без движения', 'дела и карточки выделяются и попадают в отчёт руководителю', 'дн.')}
      {num('max_file_mb', 'Максимальный размер файла', '', 'МБ')}
      <div className="row" style={{ marginTop: 12 }}><button className="btn ghost sm" onClick={exp}><Icon name="dl" />Выгрузить все данные (CSV/JSON + файлы)</button></div>
    </div>
  </div>;
}

const ROLES: Role[] = ['admin', 'manager', 'lawyer', 'operator'];
function Users() {
  const { reloadUsers } = useApp();
  const s = useLoad(() => get<User[]>('users/'));
  const [modal, setModal] = useState<{ kind: 'new' | 'block' | 'sub' | 'edit'; u?: User } | null>(null);
  const done = (msg: string) => { setModal(null); toast(msg); s.reload(true); reloadUsers(); };
  return <><div className="row" style={{ marginBottom: 12 }}><button className="btn sm" onClick={() => setModal({ kind: 'new' })}><Icon name="plus" />Сотрудник</button><span className="muted small">Замещение — временная передача дел, карточек, диалогов и сроков; по окончании доступ возвращается автоматически.</span></div>
    <View s={s}>{(list) => <div className="card np"><table><thead><tr><th>Сотрудник</th><th>Роль</th><th>Специализация</th><th>Контакты</th><th>Дел</th><th>2FA</th><th>Статус</th><th></th></tr></thead><tbody>
      {list.filter((u) => u.role !== 'ai').map((u) => <tr key={u.id}><td><b style={{ fontWeight: 500 }}>{u.full_name}</b><div className="muted small">@{u.username}</div></td><td>{u.role_label}</td><td className="muted">{u.specialization || '—'}</td><td className="small">{u.phone}<div className="muted">{u.email}</div></td><td>{u.workload}</td>
        <td>{u.has_2fa ? <span className="row"><span className="tag g">Вкл.</span><button className="btn link small" title="Сотрудник потерял телефон" onClick={async () => { if (!confirm(`Сбросить двухфакторный вход для ${u.full_name}? При следующем входе ему нужно будет настроить его заново.`)) return; try { await post(`users/${u.id}/reset-2fa/`); done('Двухфакторный вход сброшен'); } catch (e) { toastErr(e); } }}>Сбросить</button></span> : <span className={`tag ${u.twofa_required ? 'a' : ''}`}>{u.twofa_required ? 'Нужно настроить' : 'Нет'}</span>}</td>
        <td>{!u.is_active ? <span className="tag r">Заблокирован</span> : u.substitute_id ? <span className="tag a">Замещение до {dt(u.substitute_until, false)}</span> : <span className="tag g">Активен</span>}</td>
        <td><div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn ghost sm" onClick={() => setModal({ kind: 'edit', u })}>{t('common.edit')}</button>{u.is_active && <><button className="btn ghost sm" onClick={() => setModal({ kind: 'sub', u })}>Замещение</button><button className="btn ghost sm" onClick={() => setModal({ kind: 'block', u })}>Уволить</button></>}</div></td></tr>)}
    </tbody></table></div>}</View>
    {modal?.kind === 'new' || modal?.kind === 'edit' ? <UserForm u={modal.u} onClose={() => setModal(null)} onDone={() => done(modal.u ? 'Сохранено' : 'Сотрудник создан')} /> : null}
    {modal?.kind === 'block' && modal.u && <BlockModal u={modal.u} onClose={() => setModal(null)} onDone={() => done('Учётная запись заблокирована, дела переданы')} />}
    {modal?.kind === 'sub' && modal.u && <SubModal u={modal.u} onClose={() => setModal(null)} onDone={() => done('Замещение назначено')} />}
  </>;
}
function UserForm({ u, onClose, onDone }: { u?: User; onClose: () => void; onDone: () => void }) {
  const [v, setV] = useState({ username: u?.username || '', password: '', full_name: u?.full_name || '', role: (u?.role || 'lawyer') as Role, specialization: u?.specialization || '', phone: u?.phone || '', email: u?.email || '' });
  const set = (k: string, x: string) => setV({ ...v, [k]: x });
  return <Modal small onClose={onClose}><h2>{u ? 'Сотрудник' : 'Новый сотрудник'}</h2><div className="fg">
    <div className="full"><div className="lbl">ФИО</div><input className="fld" value={v.full_name} onChange={(e) => set('full_name', e.target.value)} /></div>
    <div><div className="lbl">Логин</div><input className="fld" value={v.username} disabled={!!u} onChange={(e) => set('username', e.target.value)} /></div>
    <div><div className="lbl">{u ? 'Новый пароль' : 'Пароль'}</div><PasswordInput value={v.password} onChange={(e) => set('password', e.target.value)} placeholder={u ? 'не менять' : ''} autoComplete="new-password" /></div>
    <div><div className="lbl">Роль</div><select className="fld" value={v.role} onChange={(e) => set('role', e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{t('role.' + r)}</option>)}</select></div>
    <div><div className="lbl">Специализация</div><input className="fld" value={v.specialization} onChange={(e) => set('specialization', e.target.value)} /></div>
    <div><div className="lbl">Телефон</div><input className="fld" value={v.phone} onChange={(e) => set('phone', e.target.value)} /></div>
    <div><div className="lbl">Email</div><input className="fld" value={v.email} onChange={(e) => set('email', e.target.value)} /></div></div>
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" onClick={async () => { try { const body: any = { ...v }; if (!body.password) delete body.password; if (u) { delete body.username; await patch(`users/${u.id}/`, body); } else await post('users/', body); onDone(); } catch (e) { toastErr(e); } }}>{t('common.save')}</button></div>
  </Modal>;
}
function BlockModal({ u, onClose, onDone }: { u: User; onClose: () => void; onDone: () => void }) {
  const [to, setTo] = useState<number | null>(null);
  return <Modal small onClose={onClose}><h2>Увольнение: {u.full_name}</h2>
    <div className="note w" style={{ marginBottom: 12 }}><Icon name="alert" /><div>Учётная запись будет заблокирована. Все клиенты, дела, карточки, диалоги и сроки перейдут выбранному сотруднику. История остаётся в системе.</div></div>
    <div className="lbl">Кому передать</div><UserSelect value={to} onChange={setTo} filter={(x) => x.id !== u.id} empty="Выберите сотрудника" />
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn red" disabled={!to} onClick={async () => { try { await post(`users/${u.id}/block/`, { transfer_to: to }); onDone(); } catch (e) { toastErr(e); } }}>Заблокировать и передать</button></div>
  </Modal>;
}
function SubModal({ u, onClose, onDone }: { u: User; onClose: () => void; onDone: () => void }) {
  const [to, setTo] = useState<number | null>(u.substitute_id); const [until, setUntil] = useState('');
  return <Modal small onClose={onClose}><h2>Замещение: {u.full_name}</h2>
    <div className="lbl">Замещающий сотрудник</div><UserSelect value={to} onChange={setTo} filter={(x) => x.id !== u.id} empty="Выберите сотрудника" />
    <div className="lbl" style={{ marginTop: 10 }}>До (включительно)</div><input className="fld" type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
    <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}><button className="btn ghost" onClick={onClose}>{t('common.cancel')}</button>
      <button className="btn" disabled={!to || !until} onClick={async () => { try { await post(`users/${u.id}/substitute/`, { substitute_id: to, until }); onDone(); } catch (e) { toastErr(e); } }}>Назначить</button></div>
  </Modal>;
}

const DK: [DictKind, string][] = [['case_category', 'Категории дел'], ['case_status', 'Статусы дел'], ['source', 'Источники'], ['tag', 'Теги'], ['refusal_reason', 'Причины отказа'], ['deadline_template', 'Шаблоны сроков'], ['quick_reply', 'Быстрые ответы и шаблоны']];
function Dicts() {
  const { dict, reloadDict } = useApp();
  const [kind, setKind] = useState<DictKind>('case_category'); const [name, setName] = useState(''); const [extra, setExtra] = useState('');
  const add = async () => {
    if (!name.trim()) return;
    const ex = kind === 'deadline_template' ? { days: Number(extra) || 0 } : kind === 'quick_reply' ? { text: extra || name } : {};
    try { await post('dict/', { kind, name: name.trim(), extra: ex }); setName(''); setExtra(''); reloadDict(); toast('Добавлено'); } catch (e) { toastErr(e); }
  };
  const items = dict[kind] || [];
  return <div className="grid" style={{ gridTemplateColumns: '240px 1fr' }}>
    <div className="card np">{DK.map(([k, l]) => <div key={k} className={`citem ${kind === k ? 'on' : ''}`} onClick={() => setKind(k)}><div className="t" style={{ color: 'var(--text)' }}>{l} <span className="muted small">{dict[k]?.length || 0}</span></div></div>)}</div>
    <div className="card"><h3>{DK.find((x) => x[0] === kind)?.[1]}</h3>
      {items.length === 0 ? <Empty /> : items.map((i) => <div key={i.id} className="set"><div>{i.name}<small>{kind === 'deadline_template' ? `${String(i.extra?.days ?? '')} дней` : kind === 'quick_reply' ? String(i.extra?.text || '') : kind === 'case_status' ? `код: ${i.code}${i.extra?.final ? ' · итоговый' : ''}` : ''}</small></div>
        <button className="ib" onClick={async () => { if (!confirm(`Удалить «${i.name}»?`)) return; try { await del(`dict/${i.id}/`); reloadDict(); } catch (e) { toastErr(e); } }}><Icon name="x" /></button></div>)}
      <div className="row" style={{ marginTop: 12 }}><input className="fld" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        {(kind === 'deadline_template' || kind === 'quick_reply') && <input className="fld" placeholder={kind === 'deadline_template' ? 'Дней' : 'Текст ответа'} type={kind === 'deadline_template' ? 'number' : 'text'} value={extra} onChange={(e) => setExtra(e.target.value)} />}
        <button className="btn sm" onClick={add}><Icon name="plus" />{t('common.add')}</button></div></div>
  </div>;
}
