# Law & Justice CRM — API контракт

База: `/api/`. Авторизация: `Authorization: Bearer <access>` (JWT). Типы ответов — `frontend/src/lib/types.ts`.
Ошибки: `{detail: string}` со статусом 400/401/403/404/409. 409 — бизнес-блокировка (конфликт интересов, итоговая колонка и т. п.).
WebSocket: `ws(s)://<host>/ws/events/?token=<access>` → сообщения `WsEvent`.
Файлы: `url` в `Attachment` — подписанная ссылка `/api/files/<id>/?sig=...` (живёт 1 час, без JWT).

## Auth / пользователи
| Метод | Путь | Тело / query | Ответ |
|---|---|---|---|
| POST | auth/login/ | {username, password, otp?} | LoginResponse (401 + otp_required) |
| POST | auth/refresh/ | {refresh} | {access} |
| GET | auth/me/ | | User |
| POST | auth/2fa/setup/ | | {secret, otpauth_url} |
| POST | auth/2fa/enable/ | {otp} | User |
| GET | users/ | ?role= | User[] |
| POST | users/ | {username,password,full_name,role,specialization,phone,email} (admin) | User |
| PATCH | users/{id}/ | | User |
| POST | users/{id}/block/ | {transfer_to} (admin) | {transferred: {...}} |
| POST | users/{id}/substitute/ | {substitute_id, until} (manager+) | User |

## Справочники и настройки
| GET | dict/ | | Dictionaries |
| POST | dict/ | {kind, name, code?, extra?} (admin) | DictItem |
| PATCH/DELETE | dict/{id}/ | | DictItem |
| GET/PATCH | settings/ | AppSettings (частично) | AppSettings |

## Клиенты, дела, участники, конфликты
| GET | clients/ | ?search=&kind=person|company&no_consent=1 | Client[] |
| POST | clients/ | Client поля (+ авто-проверка конфликта) | Client |
| GET/PATCH | clients/{id}/ | | Client (просмотр пишется в журнал) |
| GET | clients/{id}/timeline/ | | TimelineItem[] |
| GET | clients/{id}/related/ | | {cases: Case[], cards: CardSummary[], conversations: Conversation[], calls: Call[], files: Attachment[]} |
| POST | clients/{id}/consent/ | {status: given|revoked, channel, text} | Client |
| POST | clients/merge/ | {primary, duplicate} | Client |
| GET | clients/export/ | (admin, csv, журнал) | text/csv |
| GET | cases/ | ?status=&mine=1&search=&archived=1&court=1 | Case[] |
| POST | cases/ | {title, client, category, status?, responsible, court, is_confidential, members, parties:[{role,name,pin,phone}]} | Case (409 при конфликте → статус new) |
| GET/PATCH | cases/{id}/ | PATCH status → 409 если конфликт не решён | Case |
| GET | cases/{id}/timeline/ | | TimelineItem[] |
| POST | parties/ | {case|lead, role, name, pin, phone} | Party |
| DELETE | parties/{id}/ | | 204 |
| POST | conflicts/check/ | {name?, pin?, phone?} | ConflictCheck (subject_type=manual) |
| GET | conflicts/ | ?status=pending | ConflictCheck[] |
| POST | conflicts/{id}/decide/ | {decision: cleared|refused, comment} (manager+) | ConflictCheck |

## Сроки и календарь
| GET | deadlines/ | ?state=late|today|week|done|active&user= | Deadline[] |
| POST | deadlines/ | Deadline поля | Deadline |
| PATCH/DELETE | deadlines/{id}/ | | Deadline |
| POST | deadlines/{id}/done/ | multipart {file?} | Deadline |
| POST | deadlines/calc/ | {base_date, template_id} | {date} |
| GET | deadlines/counts/ | | {late, today, week, done, active} |
| GET | calendar/ | ?from=YYYY-MM-DD&to=YYYY-MM-DD | CalendarItem[] |
| POST | events/ | {title, kind, start, end?, case?, client?, user?} | CalendarItem |

## Договоры и оплаты
| GET | contracts/ | | Contract[] |
| POST | contracts/ | {client, case?, status, model, fee, responsible, payments:[{due_date, amount}]} | Contract |
| PATCH | contracts/{id}/ | | Contract |
| POST | payments/{id}/pay/ | {amount, paid_at?} | Payment |
| GET | finance/summary/ | | FinanceSummary |
| GET | finance/export/ | xlsx (журнал) | file |

## Доски
| GET | boards/ | ?archived=1 | BoardShort[] |
| POST | boards/ | {name, template?: leads|family|criminal|inner|blank, color?} | Board |
| GET | boards/{id}/ | ?member=&label=&due=late|week&client=&q= | Board |
| PATCH | boards/{id}/ | {name, color, is_favorite, is_archived} | BoardShort |
| POST | boards/{id}/copy/ | | Board |
| POST | boards/import-trello/ | multipart {file} (JSON экспорт Trello) | {boards, lists, cards, checklists, comments, labels, unmatched_users: string[]} |
| POST | lists/ | {board, name} | BoardList |
| PATCH | lists/{id}/ | {name, wip_limit, is_final, is_archived} | BoardList |
| POST | lists/reorder/ | {board, ids: number[]} | {ok} |
| POST | cards/ | {list, title, client?, case?, conversation?} | CardDetail |
| GET | cards/search/ | ?q= | (CardSummary & {board_name, list_name})[] |
| GET/PATCH | cards/{id}/ | title, description, due_at, start_at, priority, labels, members, client, case | CardDetail |
| POST | cards/{id}/move/ | {list, position} (409 конфликт) | CardDetail |
| POST | cards/{id}/copy/ | | CardDetail |
| POST | cards/{id}/archive/  /restore/  /subscribe/ | | CardDetail |
| POST | checklists/ | {card, title} | Checklist |
| DELETE | checklists/{id}/ | | 204 |
| POST | checklist-items/ | {checklist, text} | ChecklistItem |
| PATCH/DELETE | checklist-items/{id}/ | {done, text, assignee, due_at} | ChecklistItem |
| POST | comments/ | {card, text} (@username → упоминание) | Comment |
| POST | labels/ | {board, name, color} | Label |
| POST | attachments/ | multipart {file, card?|case?|client?|conversation?|comment?} | Attachment |
| DELETE | attachments/{id}/ | | 204 |
| POST | cards/{id}/cover/ | {attachment} | CardDetail |
| GET/POST | automations/ | ?board= | Automation[] |
| DELETE | automations/{id}/ | | 204 |

## Центр обращений
| GET | conversations/ | ?filter=all|urgent|ai|wa|g|meta|ph|unread|closed&responsible= | Conversation[] |
| GET | conversations/{id}/ | (сбрасывает unread) | ConversationDetail |
| POST | conversations/{id}/messages/ | {text, attachment?, is_note?} | Message |
| POST | conversations/{id}/mode/ | {mode} | ConversationDetail |
| POST | conversations/{id}/send-draft/ | {text?} | ConversationDetail |
| POST | conversations/{id}/assign/ | {user} | ConversationDetail |
| POST | conversations/{id}/close/ | {result: client|consult|refused|spam, reason?} | ConversationDetail |
| POST | conversations/{id}/create-card/ | {board?} | CardDetail |
| POST | conversations/{id}/create-case/ | {title?, category?} | Case (409 конфликт) |
| POST | messages/{id}/to-card/ | {card} | Attachment |
| POST | messages/{id}/rate/ | {correct: bool} | Message |
| POST | simulate/inbound/ | {channel: wa|g|meta, name, phone, text, campaign?} (admin/manager — для демо и приёмки без боевых каналов) | Conversation |

## Звонки
| GET | calls/ | | Call[] |
| GET | calls/{id}/ | | Call |
| POST | calls/{id}/recording/ | {action: play|download} → журнал | {url} |
| POST | calls/originate/ | {phone, client?} | Call |
| POST | calls/{id}/answer/ | | Call |
| POST | calls/{id}/to-ai/ | | Call |
| POST | simulate/call/ | {phone, missed?: bool} | Call (+ WS call.incoming) |

## Вебхуки (без JWT, защищены токеном)
| GET/POST | webhooks/whatsapp/ | Meta Cloud API verify + messages/statuses |
| POST | webhooks/google/?key= | Google Ads Lead Form (user_column_data) / форма сайта {name, phone, email, text, utm_*} |
| GET/POST | webhooks/meta/ | Meta Lead Ads leadgen (field_data или leadgen_id → Graph API) |
| POST | webhooks/telephony/?key= | {event: ringing|answered|ended|missed, call_id, from, to, duration?, record_url?} |

## Ассистент и AI
| POST | assistant/command/ | {text} | AssistantRun |
| POST | assistant/{id}/confirm/  /cancel/ | | AssistantRun |
| GET | assistant/ | | AssistantRun[] |
| POST | ai/undo/{audit_id}/ | (admin) | {ok} |

## Прочее
| GET | dashboard/ | | Dashboard |
| GET | reports/funnel/ | ?period=week|month|quarter | FunnelReport |
| POST | reports/ad-spend/ | {month: YYYY-MM, channel, campaign, amount} | {ok} |
| GET | reports/funnel/export/ | xlsx | file |
| GET | notifications/ | | Notification[] |
| POST | notifications/read-all/ | | {ok} |
| GET | audit/ | ?type=&limit=&offset= | {count, results: AuditEntry[]} |
| GET | export/all/ | (admin) zip: JSON + файлы | file |
| GET | search/ | ?q= | {clients, cases, cards, conversations} (до 5 каждого) |
