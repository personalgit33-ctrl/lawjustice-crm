export const money = (n: number | null | undefined) => n == null ? '—' : `${Math.round(n).toLocaleString('ru-RU').replace(/,/g, ' ')} сом`;
export const num = (n: number | null | undefined) => n == null ? '—' : Math.round(n).toLocaleString('ru-RU');
export function dt(s: string | null | undefined, withTime = true) {
  if (!s) return '—';
  const d = new Date(s); if (isNaN(+d)) return s;
  const now = new Date(); const same = d.toDateString() === now.toDateString();
  const y = new Date(now); y.setDate(now.getDate() - 1);
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  if (same) return withTime ? `Сегодня, ${time}` : 'Сегодня';
  if (d.toDateString() === y.toDateString()) return withTime ? `Вчера, ${time}` : 'Вчера';
  const date = d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
  return withTime ? `${date}, ${time}` : date;
}
export const time = (s: string) => { const d = new Date(s); return isNaN(+d) ? s : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }); };
export const dur = (sec: number) => `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
export const initials = (n: string) => n.replace(/[«»"]|ОсОО |ООО |ОАО /g, '').split(/\s+/).filter(Boolean).map((x) => x[0]).join('').slice(0, 2).toUpperCase();
export const toLocalInput = (s: string | null | undefined) => {
  if (!s) return ''; const d = new Date(s); if (isNaN(+d)) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
export const fromLocalInput = (s: string) => s ? new Date(s).toISOString() : null;
export const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const fsize = (b: number) => b > 1048576 ? `${(b / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(b / 1024))} КБ`;
