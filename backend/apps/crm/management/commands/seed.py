"""Начальные данные: справочники, сотрудники (роли), доски и демо-данные как в прототипе.

python manage.py seed            — справочники + сотрудники + демо
python manage.py seed --no-demo  — только справочники и сотрудники (боевой старт)
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boards.models import BoardList, Card, Checklist, ChecklistItem, Comment, Label
from apps.boards.services import create_board, history
from apps.comms.models import Call, Conversation, Lead, Message
from apps.crm.models import AdSpend, CalendarEvent, Case, Client, ConflictCheck, Contract, Deadline, DictItem, Party, Payment

PASSWORD = "demo12345"

DICTS = {
    "case_category": ["Семейное право", "Уголовное право", "Корпоративное право", "Земельные споры", "Гражданское право"],
    "case_status": [("new", "Новое обращение"), ("evaluation", "На первичной оценке"), ("assigned", "Назначено юристу"), ("in_work", "В работе"), ("court", "В суде / на заседании"), ("waiting", "Ожидание клиента / документов"), ("done", "Завершено", True), ("closed", "Закрыто / отменено", True)],
    "source": [("wa", "WhatsApp"), ("g", "Google"), ("meta", "Meta"), ("ph", "Телефония"), ("manual", "Вручную")],
    "tag": ["VIP", "Повторное обращение", "Рекомендация"],
    "refusal_reason": ["Дорого", "Не наш профиль", "Конфликт интересов", "Не вышел на связь", "Спам", "Другое"],
    "deadline_template": [("Апелляционная жалоба — 30 дней", 30), ("Частная жалоба — 15 дней", 15), ("Ответ на запрос — 10 дней", 10), ("Кассационная жалоба — 30 дней", 30), ("Претензионный порядок — 30 дней", 30)],
    "quick_reply": [("Приветствие", "Здравствуйте! Чем можем помочь?"), ("Стоимость консультации", "Стоимость консультации — 2 000 сом"), ("Адрес", "Адрес: г. Бишкек, ул. Киевская, 95"), ("Документы", "Пришлите, пожалуйста, документы")],
}
USERS = [
    ("admin", "Администратор системы", "admin", ""),
    ("elmira", "Эльмира Абдыкадырова", "manager", "Руководитель"),
    ("bakyt", "Бакыт Осмонов", "lawyer", "Уголовное право"),
    ("azamat", "Азамат Кадыров", "lawyer", "Семейное право"),
    ("aigul", "Айгуль Токтосунова", "lawyer", "Корпоративное право"),
    ("nurlan", "Нурлан Жумабеков", "lawyer", "Земельные споры"),
    ("meerim", "Мээрим Оторбаева", "operator", "Первая линия"),
]


class Command(BaseCommand):
    help = "Справочники, сотрудники и демо-данные"

    def add_arguments(self, parser):
        parser.add_argument("--no-demo", action="store_true")
        parser.add_argument("--reset", action="store_true", help="удалить демо-данные перед загрузкой")

    @transaction.atomic
    def handle(self, *args, **o):
        self.reset = o["reset"]
        self.dicts()
        U = self.users()
        if o["no_demo"]:
            self.stdout.write(self.style.SUCCESS("Справочники и сотрудники созданы"))
            return
        if Client.objects.exists() and not o["reset"]:
            self.stdout.write("Демо-данные уже есть (используйте --reset)")
            return
        if o["reset"]:
            for m in (Message, Conversation, Call, Lead, Card, BoardList, Label, Payment, Contract, Deadline, CalendarEvent, Party, ConflictCheck, Case, Client, AdSpend, AuditLog):
                m.objects.all().delete()
            from apps.boards.models import Board

            Board.objects.all().delete()
        self.demo(U)
        self.stdout.write(self.style.SUCCESS(f"Готово. Вход: admin / elmira / bakyt / azamat / aigul / nurlan / meerim, пароль {PASSWORD}"))

    def dicts(self):
        for kind, items in DICTS.items():
            if DictItem.objects.filter(kind=kind).exists():
                continue
            for i, it in enumerate(items):
                if kind == "case_status":
                    DictItem.objects.create(kind=kind, code=it[0], name=it[1], order=i, extra={"final": len(it) > 2})
                elif kind == "source":
                    DictItem.objects.create(kind=kind, code=it[0], name=it[1], order=i)
                elif kind == "deadline_template":
                    DictItem.objects.create(kind=kind, name=it[0], order=i, extra={"days": it[1]})
                elif kind == "quick_reply":
                    DictItem.objects.create(kind=kind, name=it[0], order=i, extra={"text": it[1]})
                else:
                    DictItem.objects.create(kind=kind, name=it, order=i)

    def users(self):
        U = {}
        for username, name, role, spec in USERS:
            u, created = User.objects.get_or_create(username=username, defaults={"full_name": name, "role": role, "specialization": spec, "email": f"{username}@lawjustice.kg", "is_staff": role == "admin", "is_superuser": role == "admin"})
            if created or self.reset:
                u.set_password(PASSWORD)
                u.is_active, u.substitute, u.substitute_until = True, None, None
                u.totp_enabled, u.totp_secret, u.recovery_codes, u.totp_last_step = False, "", [], 0
                u.failed_logins, u.locked_until = 0, None
                u.save()
            U[username] = u
        User.ai_user()
        return U

    def demo(self, U):
        now = timezone.localtime()
        today = now.date()
        tz = timezone.get_current_timezone()
        at = lambda d, h=18, m=0: timezone.make_aware(datetime.combine(today + timedelta(days=d), time(h, m)), tz)
        ago = lambda minutes: now - timedelta(minutes=minutes)

        def client(name, phone, src, resp, kind="person", consent=True, campaign="", pin=""):
            return Client.objects.create(name=name, phone=phone, source=src, responsible=U[resp], kind=kind, campaign=campaign, pin=pin,
                                         consent_status="given" if consent else "none", consent_at=now - timedelta(days=1) if consent else None,
                                         consent_channel={"wa": "WhatsApp", "g": "форма сайта", "meta": "форма Meta", "ph": "звонок"}.get(src, "") if consent else "",
                                         conflict_status="ok", city="Бишкек", last_contact_at=now - timedelta(hours=1), last_contact_channel={"wa": "WhatsApp", "g": "форма сайта", "meta": "Meta", "ph": "звонок"}[src])

        ivan = client("Иван Петров", "+996 555 12 34 56", "wa", "azamat", campaign="Юрист по разводу")
        aidana = client("Айдана Бекова", "+996 772 18 40 05", "wa", "bakyt")
        timur = client("Тимур Садыков", "+996 705 61 22 90", "g", "azamat")
        zhanyl = client("Жаныл Асанова", "+996 700 44 55 66", "g", "nurlan")
        aktoo = client("ОсОО «Ак-Тоо Строй»", "+996 312 90 00 11", "meta", "aigul", kind="company", campaign="Взыскание долгов", pin="02509201510123")
        kim = client("Алексей Ким", "+996 550 10 20 30", "ph", "bakyt", consent=False)
        mira = client("Мира Садыкова", "+996 507 33 22 11", "wa", "azamat")
        kadyrov = client("Азат Кадыров", "+996 555 40 50 60", "g", "aigul")
        unknown = Client.objects.create(name="+996 777 88 99 00", phone="+996 777 88 99 00", source="ph", responsible=U["meerim"], last_contact_at=now - timedelta(hours=14), last_contact_channel="звонок")

        def case(num, title, cl, cat, status, resp, court, opp=None, conf=False, fee=None, members=()):
            c = Case.objects.create(number=num, title=title, client=cl, category=cat, status=status, responsible=U[resp], court=court, is_confidential=conf, fee=fee, conflict_status="ok")
            c.members.set([U[resp]] + [U[m] for m in members])
            Party.objects.create(case=c, role="client", name=cl.name, phone=cl.phone, pin=cl.pin)
            if opp:
                Party.objects.create(case=c, role="opponent", name=opp[0], phone=opp[1] if len(opp) > 1 else "")
            return c

        y = today.year
        c114 = case(f"{y}-114", "Кадыров против ОсОО «Мега»", kadyrov, "Гражданское право", "in_work", "aigul", "Первомайский райсуд", ("ОсОО «Мега»",), fee=120000)
        c102 = case(f"{y}-102", "Взыскание алиментов", mira, "Семейное право", "court", "azamat", "Свердловский райсуд", ("Садыков Тимур Асанович", "+996 705 61 22 90"), fee=25000)
        c098 = case(f"{y}-098", "Раздел имущества", ivan, "Семейное право", "court", "azamat", "Ленинский райсуд", ("Петрова Анна",), fee=80000)
        c087 = case(f"{y}-087", "Защита по ст. 209 УК КР", kim, "Уголовное право", "court", "bakyt", "Октябрьский райсуд", conf=True, fee=200000)
        c121 = case(f"{y}-121", "Взыскание аванса", aktoo, "Корпоративное право", "evaluation", "aigul", "—", ("ОсОО «Курулуш Сервис»",), fee=150000)

        # конфликт: Тимур Садыков — противная сторона по делу 102
        from apps.crm.services import find_matches

        timur_lead = Lead.objects.create(client=timur, channel="g", created_at=ago(53))
        Party.objects.create(lead=timur_lead, role="opponent", name="Садыкова Мира")
        matches = find_matches(timur.name, "", timur.phone, exclude_client_id=timur.id, exclude_lead_id=timur_lead.id)
        chk = ConflictCheck.objects.create(subject_type="lead", subject_id=timur_lead.id, subject_label=timur.name, source_label="Лид · Google · форма на сайте", query={"name": timur.name, "phone": timur.phone}, matches=matches, status="pending")
        timur.conflict_status = "hit"
        timur.save()

        # Доски
        leads = create_board(template="leads")
        cases_b = create_board(template="cases")
        inner = create_board(template="inner")
        L = lambda b, i: b.lists.order_by("order")[i]
        lab = lambda b, color: b.labels.get(color=color)
        BLUE, TEAL, VIOLET, RED, GRAY, AMBER = "#2A47A1", "#0F766E", "#6D5BD0", "#D14343", "#64748B", "#B7791F"
        ai = User.ai_user()

        def card(b, li, title, color, members, due=None, src="", cl=None, case_=None, chk_items=(), done=0, ai_created=False, comments=(), summary="", conflict=None, conv=None, lead=None):
            c = Card.objects.create(list=L(b, li), title=title, position=Card.objects.filter(list=L(b, li)).count(), due_at=due, source=src, client=cl, case=case_, ai_created=ai_created, summary=summary, conflict_check=conflict, conversation=conv, lead=lead)
            c.labels.add(lab(b, color))
            c.members.set([U[m] for m in members])
            c.subscribers.set([U[m] for m in members])
            if chk_items:
                cl_ = Checklist.objects.create(card=c, title="Чек-лист")
                for i, t in enumerate(chk_items):
                    ChecklistItem.objects.create(checklist=cl_, text=t, done=i < done, order=i)
            for who, text in comments:
                Comment.objects.create(card=c, author=U[who], text=text)
            history(c, ai if ai_created else U["meerim"], "создал карточку", ai_created)
            return c

        steps = ["Связаться с клиентом", "Запросить документы", "Назначить консультацию", "Подготовить договор", "Проверить сроки", "Подготовить позицию", "Согласовать с клиентом"]

        # Диалоги
        def conv(cl, ch, mode, resp, msgs, summary, stage="Новый лид", urgent=False, draft="", unread=0, campaign="", lead=None):
            lead = lead or Lead.objects.create(client=cl, channel=ch, campaign=campaign, created_at=ago(msgs[0][2] if msgs else 60))
            cv = Conversation.objects.create(client=cl, lead=lead, channel=ch, mode=mode, status={"ai": "ai", "draft": "ai", "op": "op"}[mode], responsible=U[resp], summary=summary, stage=stage, urgent=urgent, draft=draft, unread=unread,
                                             external_id="".join(x for x in cl.phone if x.isdigit()) if ch == "wa" else "", created_at=ago(msgs[0][2] if msgs else 60))
            for author, text, mins, *rest in msgs:
                Message.objects.create(conversation=cv, author=author, text=text, user=U[rest[0]] if rest and rest[0] else None, created_at=ago(mins), delivery="delivered" if author in ("ai", "op") else "", template=bool(len(rest) > 1 and rest[1]))
            last = msgs[-1][2] if msgs else 60
            cl_msgs = [m for m in msgs if m[0] == "client"]
            Conversation.objects.filter(id=cv.id).update(updated_at=ago(last), last_client_message_at=ago(cl_msgs[-1][2]) if cl_msgs else None, first_response_at=ago(msgs[1][2]) if len(msgs) > 1 else None)
            return cv

        cv_ivan = conv(ivan, "wa", "ai", "azamat", [
            ("client", "Здравствуйте, мне нужна помощь по разводу. Есть ребёнок и совместная квартира.", 12),
            ("ai", "Здравствуйте, Иван! Вас приветствует Law & Justice, на связи виртуальный ассистент. Перед консультацией уточню пару моментов. Продолжая переписку, вы соглашаетесь с политикой обработки персональных данных: lawjustice.kg/privacy. Брак зарегистрирован в Кыргызстане? Сколько лет ребёнку?", 12),
            ("client", "Да, в Бишкеке. Сыну 7 лет. Квартира куплена в браке.", 10),
            ("client", "Вот свидетельство о браке", 9),
            ("ai", "Спасибо, документ получен. Консультации по семейным делам ведёт Азамат Кадыров. Удобно завтра в 11:00 или в 15:00?", 8),
        ], "Развод, сын 7 лет, квартира приобретена в браке, брак зарегистрирован в Бишкеке. Нужна консультация по разводу и разделу имущества.", unread=2, campaign="Юрист по разводу")
        cv_ivan.ai_state = {"step": 2, "category": "Семейное право", "privacy_sent": True, "lawyer": U["azamat"].id, "slots": [at(1, 11).isoformat(), at(1, 15).isoformat()]}
        cv_ivan.save(update_fields=["ai_state"])
        from django.core.files.base import ContentFile
        from apps.crm.models import Attachment

        att = Attachment(name="Свидетельство_о_браке.png", mime="image/png", conversation=cv_ivan, client=ivan)
        att.file.save("svidetelstvo.png", ContentFile(_png()), save=False)
        att.size = att.file.size
        att.save()
        Message.objects.filter(conversation=cv_ivan, text="Вот свидетельство о браке").update(attachment=att)

        conv(aidana, "wa", "op", "bakyt", [
            ("client", "Здравствуйте! Брата сегодня утром задержали, сейчас в РОВД, нужен адвокат срочно", 3),
            ("sys", f"Срочное обращение: диалог передан сотруднику, уведомлён руководитель · {ago(3):%H:%M}", 3),
            ("op", "Айдана, здравствуйте, это адвокат Бакыт Осмонов. Подскажите, какой РОВД и ФИО брата? Выезжаю в течение часа.", 1, "bakyt"),
        ], "Задержание родственника клиента, требуется защитник сегодня. Передано Бакыту Осмонову.", stage="Срочно", urgent=True, unread=1)
        cv_timur = conv(timur, "g", "draft", "azamat", [
            ("client", "Заявка с сайта: «Хочу разделить имущество с бывшей супругой, Садыковой Мирой. Нужна консультация».", 53),
            ("sys", f"Проверка конфликта интересов: найдено совпадение — «Садыкова Мира» является клиентом (дело № {y}-102, алименты)", 53),
        ], "Раздел имущества с бывшей супругой. Противная сторона — действующий клиент компании. Требуется решение руководителя.",
            draft="Здравствуйте, Тимур! Спасибо за обращение в Law & Justice. Ваша заявка принята, специалист свяжется с вами в течение рабочего дня.", unread=1, lead=timur_lead)
        cv_zh = conv(zhanyl, "g", "op", "nurlan", [
            ("client", "Заявка с сайта: «Сосед захватил часть участка, нужна консультация». Телефон: +996 700 44 55 66", 95),
            ("sys", "Мээрим Оторбаева взяла в работу", 93),
            ("op", "Здравствуйте, Жаныл! Это Мээрим из Law & Justice. Могу перезвонить вам в течение 15 минут?", 90, "meerim"),
        ], "Спор с соседом о границах участка. Нужна консультация по земельному праву.")
        cv_ak = conv(aktoo, "meta", "ai", "aigul", [
            ("client", "Заявка из Instagram: «Подрядчик не вернул аванс 1,2 млн сом»", 60 * 16),
            ("ai", "Здравствуйте! Уточните, пожалуйста: есть ли подписанный договор подряда и документы о перечислении аванса?", 60 * 16 - 1),
            ("client", "Да, договор есть, платёжки тоже", 60 * 16 - 18),
        ], "Юрлицо. Взыскание аванса 1,2 млн сом с подрядчика. Договор и платёжные документы есть.", stage="Квалификация", unread=1, campaign="Взыскание долгов")
        cv_unk = conv(unknown, "ph", "op", "meerim", [
            ("sys", "Пропущенный звонок 19:48 (нерабочее время)", 60 * 14),
            ("ai", "Здравствуйте! Вы звонили в Law & Justice. Мы работаем пн–пт с 9:00 до 18:00 и перезвоним вам утром. Можете коротко описать вопрос здесь.", 60 * 14 - 1, None, True),
            ("sys", "Создана задача «Перезвонить» для Мээрим Оторбаевой, срок — сегодня 10:00", 60 * 14 - 1),
        ], "Пропущенный звонок вне рабочего времени. Отправлено сообщение по шаблону, создана задача «Перезвонить».", stage="Перезвонить")

        # Карточки
        c_ivan = card(leads, 0, "Иван Петров — развод, раздел имущества", BLUE, ["azamat"], at(0, 18), "wa", ivan, chk_items=steps[:3], done=1, ai_created=True, comments=[("azamat", "Посмотрел свидетельство, консультацию проведу сам."), ("meerim", "@azamat клиент просил после обеда")], summary=cv_ivan.summary, conv=cv_ivan, lead=cv_ivan.lead)
        att.card = c_ivan
        att.save(update_fields=["card"])
        card(leads, 0, "Тимур Садыков — раздел имущества", BLUE, ["azamat"], at(1), "g", timur, chk_items=steps[:2], conflict=chk, comments=[("meerim", "Заявка с сайта, ждёт решения по конфликту")], conv=cv_timur, lead=timur_lead)
        card(leads, 0, "Жаныл Асанова — спор о границах участка", TEAL, ["nurlan"], at(1), "g", zhanyl, chk_items=steps[:2], conv=cv_zh, lead=cv_zh.lead)
        card(leads, 1, "ОсОО «Ак-Тоо Строй» — взыскание аванса с подрядчика", VIOLET, ["aigul"], at(1), "meta", aktoo, chk_items=steps[:4], done=2, comments=[("aigul", "Запросила договор подряда"), ("aigul", "Платёжки получены")], conv=cv_ak, lead=cv_ak.lead, summary=cv_ak.summary)
        card(leads, 2, "Алексей Ким — защита, ст. 209 УК КР", RED, ["bakyt"], at(3, 11), "ph", kim, case_=c087, chk_items=steps[:2], done=1, ai_created=True)
        card(leads, 3, "Мира Садыкова — алименты", BLUE, ["azamat"], None, "wa", mira, case_=c102, chk_items=steps[:3], done=3)
        card(leads, 0, "Перезвонить: +996 777 88 99 00", GRAY, ["meerim"], at(0, 10), "ph", unknown, ai_created=True, conv=cv_unk, lead=cv_unk.lead)
        card(cases_b, 0, f"№ {y}-114 · Кадыров против ОсОО «Мега»", VIOLET, ["aigul"], at(2), cl=kadyrov, case_=c114, chk_items=steps, done=4)
        card(cases_b, 1, f"№ {y}-098 · раздел имущества Петровых", BLUE, ["azamat"], at(9), cl=ivan, case_=c098, chk_items=steps[:3], done=3)
        card(cases_b, 2, f"№ {y}-087 · Ким, ст. 209 УК КР", RED, ["bakyt"], at(-1), cl=kim, case_=c087, chk_items=steps[:4], done=2)
        card(inner, 0, "Обновить шаблон договора оказания услуг", GRAY, ["meerim"], at(4), chk_items=["Собрать замечания", "Согласовать с руководителем", "Загрузить в систему"])
        card(inner, 1, "Сверка оплат за месяц", AMBER, ["aigul"], at(1), chk_items=["Выгрузить поступления", "Сверить с договорами"], done=1)

        # Сроки
        D = lambda **k: Deadline.objects.create(**k)
        D(title="Подготовить ходатайство о прекращении", type="procedural", case=c087, court="Октябрьский райсуд г. Бишкек", judge="Сыдыков Н.", responsible=U["bakyt"], backup=U["meerim"], due_at=at(-1, 18), basis="Определение суда")
        D(title="Судебное заседание", type="hearing", case=c087, court="Октябрьский райсуд", room="4", judge="Сыдыков Н.", responsible=U["bakyt"], backup=U["azamat"], due_at=at(0, 14, 30), basis="Повестка")
        D(title="Подача искового заявления", type="procedural", case=c114, court="Первомайский райсуд", responsible=U["aigul"], backup=U["meerim"], due_at=at(2), basis="Претензия без ответа, 30 дн.")
        D(title="Апелляционная жалоба", type="procedural", case=c098, court="Бишкекский горсуд", responsible=U["azamat"], backup=U["aigul"], due_at=at(4), basis="Решение получено")
        D(title="Оплата 2-го этапа по договору", type="contract", case=c121, responsible=U["aigul"], backup=U["meerim"], due_at=at(6), basis="Договор № 45")
        D(title="Судебное заседание", type="hearing", case=c098, court="Ленинский райсуд", room="2", judge="Абдиева Г.", responsible=U["azamat"], backup=U["nurlan"], due_at=at(9, 10), basis="Повестка")
        D(title="Отзыв на иск", type="procedural", case=c102, court="Свердловский райсуд", judge="Токтогулова А.", responsible=U["azamat"], backup=U["meerim"], due_at=at(-3), basis="Определение", done_at=now - timedelta(days=3), done_by=U["azamat"])

        # Календарь
        E = lambda **k: CalendarEvent.objects.create(**k)
        E(title="Консультация · Петров", kind="consultation", start=at(1, 11), end=at(1, 11, 40), client=ivan, user=U["azamat"], created_by_ai=True)
        E(title="Консультация · Асанова", kind="consultation", start=at(2, 14), end=at(2, 14, 40), client=zhanyl, user=U["nurlan"])
        E(title="Консультация · Ким", kind="consultation", start=at(3, 11), end=at(3, 11, 40), client=kim, user=U["bakyt"], case=c087, created_by_ai=True)
        E(title="Встреча с ОсОО «Ак-Тоо Строй»", kind="meeting", start=at(5, 16), client=aktoo, user=U["aigul"])

        # Договоры и оплаты
        def contract(cl, cs, model, fee, resp, pays):
            ct = Contract.objects.create(client=cl, case=cs, status="signed", model=model, fee=fee, responsible=U[resp], signed_at=today - timedelta(days=30))
            for d, amount, paid in pays:
                Payment.objects.create(contract=ct, due_date=today + timedelta(days=d), amount=amount, paid_amount=paid, paid_at=(today - timedelta(days=max(1, -d))) if paid else None)
            return ct

        contract(aktoo, c121, "staged", 150000, "aigul", [(-20, 50000, 50000), (6, 50000, 0), (36, 50000, 0)])
        contract(ivan, c098, "fixed", 80000, "azamat", [(-40, 40000, 40000), (-12, 40000, 0)])
        contract(kadyrov, c114, "staged", 120000, "aigul", [(-25, 60000, 60000), (-4, 60000, 0)])
        contract(mira, c102, "subscription", 25000, "azamat", [(-60, 25000, 25000), (-30, 25000, 25000), (-2, 25000, 25000), (2, 25000, 0)])
        contract(kim, c087, "fixed", 200000, "bakyt", [(-15, 88000, 88000), (-2, 112000, 0)])
        Contract.objects.create(client=ivan, status="sent", model="fixed", fee=60000, responsible=U["azamat"])

        # Звонки
        Call.objects.create(client=kim, phone=kim.phone, direction="in", status="answered", handled_by_ai=True, case=c087, started_at=now - timedelta(days=2, hours=1), duration=272,
                            summary="Клиент сообщил о возбуждении уголовного дела по ст. 209 УК КР, вызов к следователю в пятницу. Записан на консультацию к Бакыту Осмонову. Созданы карточка и задача «Подготовить консультацию».",
                            transcript=[{"speaker": "Ассистент", "text": "Law & Justice, здравствуйте. Разговор записывается, на линии виртуальный ассистент. Чем могу помочь?"}, {"speaker": "Клиент", "text": "Здравствуйте, мне нужен адвокат, на меня завели дело…"}, {"speaker": "Ассистент", "text": "Понимаю. Подскажите, по какой статье и на какой стадии дело?"}, {"speaker": "Клиент", "text": "Двести девятая, вызывают к следователю в пятницу."}],
                            record_url="https://example.com/rec/kim.mp3")
        Call.objects.create(client=zhanyl, phone=zhanyl.phone, direction="out", status="answered", user=U["meerim"], started_at=ago(85), duration=370,
                            summary="Уточнены границы участка, документы на землю есть (госакт). Консультация с Нурланом Жумабековым через 2 дня в 14:00.",
                            transcript=[{"speaker": "Мээрим", "text": "Жаныл, добрый день, Law & Justice, вы оставляли заявку…"}, {"speaker": "Клиент", "text": "Да, сосед поставил забор на моей земле."}], record_url="https://example.com/rec/asanova.mp3")
        Call.objects.create(client=unknown, phone=unknown.phone, direction="in", status="missed", started_at=now - timedelta(hours=14),
                            summary="Пропущенный звонок вне рабочего времени. Клиенту отправлено сообщение WhatsApp по шаблону, создана задача «Перезвонить».")

        # Реклама
        m = today.strftime("%Y-%m")
        for ch, camp, amount in (("g", "Юрист по разводу", 22000), ("meta", "Взыскание долгов", 18000), ("meta", "Семейные споры", 20000)):
            AdSpend.objects.create(month=m, channel=ch, campaign=camp, amount=amount)
        for name, ch, camp, status, reason, days in (
            ("Ольга Ли", "g", "Юрист по разводу", "refused", "Дорого", 3), ("Нурбек А.", "meta", "Семейные споры", "refused", "Не вышел на связь", 5),
            ("Эрмек Т.", "g", "Юрист по разводу", "consultation", "", 6), ("Саида К.", "meta", "Взыскание долгов", "refused", "Не наш профиль", 8),
            ("Спам-заявка", "meta", "Семейные споры", "spam", "Спам", 2), ("Руслан М.", "wa", "", "refused", "Дорого", 4),
        ):
            cl = Client.objects.create(name=name, phone=f"+996 70{days} {days}0 {days}{days} 1{days}", source=ch, campaign=camp)
            Lead.objects.create(client=cl, channel=ch, campaign=camp, status=status, refusal_reason=reason, created_at=now - timedelta(days=days))

        # Журнал
        for actor, action, obj, typ, ai_ in (
            (U["elmira"], "Открыла карточку дела", f"№ {y}-087 · Ким А. (конфиденциально)", "view", False),
            (None, "Передал диалог сотруднику: признаки срочности", "Айдана Бекова · WhatsApp", "ai", True),
            (None, "Создал карточку, заполнил поля и резюме", "Иван Петров — развод", "ai", True),
            (U["bakyt"], "Прослушал запись звонка", "Алексей Ким", "record", False),
            (None, "Проверка конфликта интересов: совпадение", f"Тимур Садыков ↔ дело № {y}-102", "check", False),
        ):
            AuditLog.objects.create(actor=actor, actor_label="Ассистент" if ai_ else (str(actor) if actor else "Система"), is_ai=ai_, action=action, object_label=obj, type=typ)


def _png():
    import base64

    # 1×1 светло-синий PNG — заглушка «фото документа» для демо
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==")
