import { ru, type Key } from './ru';
import { kg } from './kg';

type Lang = 'ru' | 'kg';
const dicts: Record<Lang, Partial<Record<Key, string>>> = { ru, kg };
let lang: Lang = 'ru';
try { const l = typeof window !== 'undefined' ? localStorage.getItem('lj_lang') : null; if (l === 'kg') lang = 'kg'; } catch {}

export function setLang(l: Lang) { lang = l; try { localStorage.setItem('lj_lang', l); } catch {} }
export function t(key: Key | string, vars?: Record<string, string | number>): string {
  let s = (dicts[lang] as Record<string, string>)[key] ?? (ru as Record<string, string>)[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
  return s;
}
export type { Key };
