import type { Role } from './types';

export type Section = 'dashboard' | 'inbox' | 'boards' | 'calls' | 'deadlines' | 'assistant' | 'clients' | 'cases' | 'conflicts' | 'calendar' | 'finance' | 'reports' | 'audit' | 'settings';

const ALL: Section[] = ['dashboard', 'inbox', 'boards', 'calls', 'deadlines', 'assistant', 'clients', 'cases', 'conflicts', 'calendar', 'finance', 'reports', 'audit', 'settings'];
const DENY: Record<Role, Section[]> = {
  admin: [],
  manager: ['settings'],
  lawyer: ['assistant', 'reports', 'audit', 'settings'],
  operator: ['assistant', 'finance', 'reports', 'audit', 'settings'],
  ai: ALL,
};
export const can = (role: Role | undefined, s: Section) => !!role && !DENY[role].includes(s);
export const isManager = (role?: Role) => role === 'admin' || role === 'manager';
export const sectionOf = (path: string): Section | null => {
  const seg = path.split('/')[1] as Section;
  return ALL.includes(seg) ? seg : null;
};
