// Единый контракт фронтенда и бэкенда Law & Justice CRM.
// Все даты — ISO 8601 строки. Все id — number. Пагинации нет (списки массивом), кроме /audit/ (limit/offset).

export type Role = 'admin' | 'manager' | 'lawyer' | 'operator' | 'ai';
export type Channel = 'wa' | 'g' | 'meta' | 'ph' | 'manual';

export interface User {
  id: number;
  username: string;
  full_name: string;
  initials: string;
  role: Role;
  role_label: string;
  specialization: string;
  phone: string;
  email: string;
  is_active: boolean;
  has_2fa: boolean;
  twofa_required: boolean; // роль обязана иметь 2FA (admin, manager)
  recovery_left: number; // осталось резервных кодов
  substitute_id: number | null;
  substitute_until: string | null;
  workload: number; // активных дел
}

export interface LoginResponse { access: string; refresh: string; user: User; recovery_codes?: string[]; recovery_left?: number }
// Шаг 1 входа может вернуть: 401 {otp_required, mfa_token} или 403 {setup_required, mfa_token}
export interface TwoFASetup { secret: string; otpauth_url: string; qr_svg: string }
// 401 c { detail, otp_required: true } — нужен код 2FA

export interface DictItem { id: number; kind: DictKind; code: string; name: string; order: number; extra: Record<string, unknown> }
export type DictKind = 'case_category' | 'case_status' | 'source' | 'tag' | 'refusal_reason' | 'deadline_template' | 'quick_reply';
export type Dictionaries = Record<DictKind, DictItem[]>;
// deadline_template.extra = { days: number }; case_status.extra = { final?: boolean }

export type ConflictStatus = 'none' | 'ok' | 'hit' | 'cleared' | 'refused';

export interface Client {
  id: number;
  kind: 'person' | 'company';
  name: string;
  city: string;
  phone: string;
  email: string;
  pin: string; // ПИН / ИНН (маскируется для ролей без доступа)
  source: Channel;
  campaign: string;
  responsible: number | null;
  responsible_name: string;
  notes: string;
  consent_status: 'none' | 'given' | 'revoked';
  consent_at: string | null;
  consent_channel: string;
  conflict_status: ConflictStatus;
  cases_count: number;
  last_contact_at: string | null;
  last_contact_label: string;
  created_at: string;
}

export interface TimelineItem { id: string; kind: 'message' | 'call' | 'case' | 'card' | 'comment' | 'file' | 'audit'; text: string; actor: string; is_ai: boolean; created_at: string; link?: string }

export interface Party { id: number; case: number | null; lead: number | null; role: 'client' | 'opponent' | 'third'; name: string; pin: string; phone: string }

export interface Case {
  id: number;
  number: string;
  title: string;
  client: number;
  client_name: string;
  category: string;
  status: string; // код из case_status
  status_label: string;
  responsible: number | null;
  responsible_name: string;
  members: number[];
  court: string;
  is_confidential: boolean;
  restricted: boolean; // true — пользователь видит факт дела, но не материалы
  opponents: string; // через запятую, для таблицы
  parties: Party[];
  nearest_deadline: string | null;
  nearest_deadline_state: DeadlineState | null;
  conflict_status: ConflictStatus;
  is_archived: boolean;
  fee: number | null;
  created_at: string;
  updated_at: string;
  stale: boolean; // нет движения > 7 дней
}

export interface ConflictMatch { party_name: string; role: 'client' | 'opponent' | 'third'; role_label: string; case_id: number | null; case_number: string; case_title: string; client_name: string; responsible_name: string; basis: string }
export interface ConflictCheck {
  id: number;
  subject_label: string;
  subject_type: 'client' | 'lead' | 'case' | 'card' | 'manual';
  query: { name?: string; pin?: string; phone?: string };
  matches: ConflictMatch[];
  status: 'ok' | 'pending' | 'cleared' | 'refused';
  decision_comment: string;
  decided_by_name: string;
  decided_at: string | null;
  created_at: string;
  source_label: string;
}

export type DeadlineState = 'late' | 'today' | 'week' | 'later' | 'done';
export interface Deadline {
  id: number;
  title: string;
  type: 'hearing' | 'procedural' | 'execution' | 'contract' | 'internal';
  type_label: string;
  case: number | null;
  case_label: string;
  is_confidential: boolean;
  due_at: string;
  due_label: string;
  court: string;
  judge: string;
  room: string;
  responsible: number | null;
  backup: number | null;
  basis: string;
  state: DeadlineState;
  done_at: string | null;
  done_file: Attachment | null;
  card: number | null;
}

export interface CalendarItem { id: string; title: string; kind: 'hearing' | 'deadline' | 'consultation' | 'meeting' | 'card'; start: string; end: string | null; link: string; user_id: number | null }

export interface Payment { id: number; contract: number; due_date: string; amount: number; paid_amount: number; paid_at: string | null; overdue_days: number }
export interface Contract {
  id: number;
  client: number;
  client_name: string;
  case: number | null;
  case_number: string;
  status: 'none' | 'sent' | 'signed';
  model: 'fixed' | 'staged' | 'subscription';
  model_label: string;
  fee: number;
  paid: number;
  debt: number;
  next_payment_label: string;
  next_payment_overdue: boolean;
  responsible: number | null;
  payments: Payment[];
}
export interface FinanceSummary { received_month: number; received_prev_month: number; expected_next: number; receivables: number; overdue_count: number; contracts_signed: number; avg_fee: number; by_category: { name: string; amount: number; share: number }[] }

export interface Label { id: number; name: string; color: string }
export interface CardSummary {
  id: number;
  title: string;
  list: number;
  position: number;
  labels: number[];
  members: number[];
  due_at: string | null;
  due_label: string;
  due_state: 'late' | 'soon' | 'done' | null;
  checklist: [number, number];
  attachments_count: number;
  comments_count: number;
  is_confidential: boolean;
  conflict_status: ConflictStatus;
  source: Channel | '';
  client_name: string;
  cover_url: string | null;
  ai_created: boolean;
  priority: 'low' | 'normal' | 'high' | 'urgent';
}
export interface ChecklistItem { id: number; text: string; done: boolean; assignee: number | null; due_at: string | null }
export interface Checklist { id: number; title: string; items: ChecklistItem[] }
export interface Attachment { id: number; name: string; size: number; mime: string; is_image: boolean; url: string; created_at: string; uploaded_by_name: string }
export interface Comment { id: number; author: number | null; author_name: string; is_ai: boolean; text: string; created_at: string; attachments: Attachment[] }
export interface HistoryItem { id: number; actor_name: string; is_ai: boolean; text: string; created_at: string }
export interface CardDetail extends CardSummary {
  board: number;
  board_name: string;
  list_name: string;
  description: string;
  start_at: string | null;
  client: number | null;
  case: number | null;
  case_number: string;
  conversation: number | null;
  opponent: string;
  summary: string; // AI-резюме
  checklists: Checklist[];
  attachments: Attachment[];
  comments: Comment[];
  history: HistoryItem[];
  subscribed: boolean;
  is_archived: boolean;
  conflict_check: number | null;
}
export interface BoardList { id: number; name: string; order: number; wip_limit: number | null; is_final: boolean; cards: CardSummary[] }
export interface BoardShort { id: number; name: string; color: string; is_favorite: boolean; is_archived: boolean; cards_count: number }
export interface Board extends BoardShort { lists: BoardList[]; labels: Label[]; automations: Automation[] }
export interface Automation { id: number; board: number; list: number; action: 'assign' | 'set_due_days' | 'add_checklist' | 'notify' | 'set_case_status'; params: Record<string, unknown>; is_active: boolean }

export type ConvMode = 'ai' | 'draft' | 'op';
export type ConvStatus = 'new' | 'ai' | 'op' | 'waiting' | 'closed';
export interface Conversation {
  id: number;
  client: number;
  client_name: string;
  phone: string;
  channel: Channel;
  mode: ConvMode;
  status: ConvStatus;
  unread: number;
  urgent: boolean;
  last_message: string;
  last_at: string;
  last_label: string;
  responsible: number | null;
  responsible_name: string;
  wa_window_seconds: number | null; // null — не WhatsApp; 0 — окно закрыто
  source_label: string;
  stage: string;
  consent_label: string;
  consent_ok: boolean;
  conflict_status: ConflictStatus;
  summary: string;
  draft: string;
  lead: number | null;
  related: { cards: { id: number; title: string; board_name: string }[]; cases: { id: number; number: string; title: string }[]; calls: number; files: number };
}
export interface Message {
  id: number;
  author: 'client' | 'ai' | 'op' | 'sys' | 'note';
  author_name: string;
  text: string;
  attachment: Attachment | null;
  created_at: string;
  delivery: 'sent' | 'delivered' | 'read' | 'failed' | '';
  template: boolean;
  rating: boolean | null; // оценка ответа AI
}
export interface ConversationDetail extends Conversation { messages: Message[] }

export interface Call {
  id: number;
  client: number | null;
  client_name: string;
  phone: string;
  direction: 'in' | 'out';
  handled_by: 'ai' | 'user' | 'none';
  handled_by_name: string;
  status: 'answered' | 'missed' | 'transferred' | 'ringing';
  started_at: string;
  started_label: string;
  duration: number; // секунды
  has_recording: boolean;
  summary: string;
  transcript: { speaker: string; text: string }[];
  is_confidential: boolean;
}
export interface IncomingCallEvent { call_id: number; phone: string; client: Client | null; open_cards: string[]; last_contact: string; nearest: string }

export interface AssistantStep { tool: string; label: string; detail: string; needs_confirm: boolean; status: 'done' | 'pending' | 'cancelled' | 'denied' }
export interface AssistantRun { id: number; command: string; created_at: string; steps: AssistantStep[]; result: string; state: 'done' | 'awaiting_confirm' | 'cancelled' | 'denied'; engine: 'claude' | 'rules' }

export interface Notification { id: number; kind: string; text: string; link: string; is_read: boolean; created_at: string }
export interface AuditEntry { id: number; created_at: string; actor_name: string; is_ai: boolean; action: string; object_label: string; type: 'view' | 'export' | 'ai' | 'record' | 'access' | 'change' | 'check'; type_label: string; can_undo: boolean }

export interface Dashboard {
  kpis: { new_today: number; new_yesterday: number; first_response_sec: number; active_cases: number; cases_deadline_week: number; received_month: number; received_growth_pct: number; receivables: number; overdue_payments: number };
  deadlines: Deadline[];
  attention: { level: 'r' | 'a' | 'b'; title: string; text: string; link: string }[];
  channels: { channel: Channel; count: number }[];
  workload: { user: number; name: string; initials: string; cases: number; pct: number }[];
  first_line: { ai_share_pct: number; handed_pct: number; consultations: number; ai_wrong: number };
  missed_calls: number;
  stale_items: number;
}

export interface FunnelReport {
  period: string;
  totals: { leads: number; consultations: number; contracts: number; paid: number; spend: number; cost_per_client: number | null; ai_share_pct: number };
  rows: { channel: Channel; campaign: string; spend: number; leads: number; consultations: number; contracts: number; paid_amount: number; cost_per_lead: number | null; cost_per_client: number | null }[];
  funnel: { name: string; count: number; pct: number }[];
  refusals: { name: string; count: number }[];
}

export interface AppSettings {
  integrations: Record<string, { enabled: boolean; label: string; info: string; configured: boolean }>;
  ai: { chat_247: boolean; calls_after_hours: boolean; draft_mode_wa: boolean; disclose_ai: boolean; masking: boolean; skip_confidential: boolean; no_legal_advice: boolean; monthly_limit_usd: number; spent_usd: number };
  security: { require_2fa_admin: boolean; idle_logout_min: number; export_admin_only: boolean; view_log: boolean; recordings_retention_months: number; archive_years: number; stale_days: number; max_file_mb: number };
  knowledge_base: string;
  reminders_days: number[];
  work_hours: { start: string; end: string; days: number[] };
}

export interface WsEvent { type: 'card.moved' | 'card.updated' | 'card.created' | 'board.updated' | 'message.new' | 'conversation.updated' | 'call.incoming' | 'call.updated' | 'notification'; payload: any }
