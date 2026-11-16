"""Сценарии двухфакторного входа: python tests/twofa_api.py [base_url]"""
import sys
import time

import pyotp
import requests

B = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000") + "/api/"
F = []


def ok(name, cond, extra=""):
    print("OK  " if cond else "FAIL", name, extra)
    if not cond:
        F.append(name)


def wait_next_step():
    time.sleep(31 - (time.time() % 30) + 0.5)


P = {"username": "elmira", "password": "demo12345"}
# 1. Руководитель без 2FA → обязательная настройка, JWT не выдаётся
r = requests.post(B + "auth/login/", json=P)
ok("manager без 2FA → 403 setup_required", r.status_code == 403 and r.json().get("setup_required") and "access" not in r.json())
tok = r.json()["mfa_token"]
ok("чужой этап токена отклонён", requests.post(B + "auth/login/verify/", json={"mfa_token": tok, "code": "000000"}).status_code == 401)
st = requests.post(B + "auth/2fa/enroll/start/", json={"mfa_token": tok}).json()
ok("выдан ключ и QR", st.get("secret") and st.get("qr_svg", "").startswith("data:image/svg+xml"))
totp = pyotp.TOTP(st["secret"])
ok("неверный код при настройке → 400", requests.post(B + "auth/2fa/enroll/finish/", json={"mfa_token": tok, "code": "123456"}).status_code == 400)
r = requests.post(B + "auth/2fa/enroll/finish/", json={"mfa_token": tok, "code": totp.now()})
d = r.json()
ok("настройка завершена → JWT + 8 резервных кодов", r.status_code == 200 and d.get("access") and len(d.get("recovery_codes", [])) == 8)
codes = d["recovery_codes"]
ok("me: has_2fa", requests.get(B + "auth/me/", headers={"Authorization": "Bearer " + d["access"]}).json()["has_2fa"])

# 2. Повторный вход: пароль → код
r = requests.post(B + "auth/login/", json=P)
ok("повторный вход → 401 otp_required, без JWT", r.status_code == 401 and r.json().get("otp_required") and "access" not in r.json())
tok = r.json()["mfa_token"]
ok("тот же код второй раз не принимается (replay)", requests.post(B + "auth/login/verify/", json={"mfa_token": tok, "code": totp.now()}).status_code == 401)
wait_next_step()
r = requests.post(B + "auth/login/verify/", json={"mfa_token": tok, "code": totp.now()})
ok("новый код → JWT", r.status_code == 200 and r.json().get("access"))
access = r.json()["access"]
H = {"Authorization": "Bearer " + access}

# 3. Резервный код
r = requests.post(B + "auth/login/", json=P)
tok = r.json()["mfa_token"]
r = requests.post(B + "auth/login/verify/", json={"mfa_token": tok, "code": codes[0].lower()})
ok("вход по резервному коду", r.status_code == 200 and r.json().get("recovery_left") == 7)
r = requests.post(B + "auth/login/", json=P)
ok("резервный код одноразовый", requests.post(B + "auth/login/verify/", json={"mfa_token": r.json()["mfa_token"], "code": codes[0]}).status_code == 401)

# 4. Отключить нельзя (обязательная роль)
ok("руководитель не может отключить 2FA", requests.post(B + "auth/2fa/disable/", json={"code": codes[1]}, headers=H).status_code == 403)

# 5. Новые резервные коды
wait_next_step()
r = requests.post(B + "auth/2fa/recovery-codes/", json={"code": totp.now()}, headers=H)
ok("перевыпуск резервных кодов", r.status_code == 200 and len(r.json()["recovery_codes"]) == 8)

# 6. Юрист: 2FA необязательна, включает и отключает сам
r = requests.post(B + "auth/login/", json={"username": "bakyt", "password": "demo12345"})
ok("юрист без 2FA входит сразу", r.status_code == 200 and r.json().get("access"))
LH = {"Authorization": "Bearer " + r.json()["access"]}
st = requests.post(B + "auth/2fa/setup/", headers=LH).json()
lt = pyotp.TOTP(st["secret"])
r = requests.post(B + "auth/2fa/enable/", json={"otp": lt.now()}, headers=LH)
ok("юрист включил 2FA", r.status_code == 200 and r.json()["has_2fa"] and len(r.json()["recovery_codes"]) == 8)
lcodes = r.json()["recovery_codes"]
r = requests.post(B + "auth/2fa/disable/", json={"code": lcodes[0]}, headers=LH)
ok("юрист отключил 2FA резервным кодом", r.status_code == 200 and not r.json()["has_2fa"])

# 7. Блокировка после 5 неверных кодов
r = requests.post(B + "auth/login/", json={"username": "bakyt", "password": "demo12345"})
requests.post(B + "auth/2fa/setup/", headers=LH)  # не важно
# включим заново
st = requests.post(B + "auth/2fa/setup/", headers=LH).json(); lt = pyotp.TOTP(st["secret"])
requests.post(B + "auth/2fa/enable/", json={"otp": lt.now()}, headers=LH)
tok = requests.post(B + "auth/login/", json={"username": "bakyt", "password": "demo12345"}).json()["mfa_token"]
last = None
for _ in range(5):
    last = requests.post(B + "auth/login/verify/", json={"mfa_token": tok, "code": "000000"})
ok("5 неверных кодов → блокировка 423", last.status_code == 423)
ok("во время блокировки даже пароль не пускает", requests.post(B + "auth/login/", json={"username": "bakyt", "password": "demo12345"}).status_code == 423)

# 8. Админ сбрасывает 2FA сотруднику
r = requests.post(B + "auth/login/", json={"username": "admin", "password": "demo12345"})
atok = r.json()["mfa_token"]
st = requests.post(B + "auth/2fa/enroll/start/", json={"mfa_token": atok}).json()
AH = {"Authorization": "Bearer " + requests.post(B + "auth/2fa/enroll/finish/", json={"mfa_token": atok, "code": pyotp.TOTP(st["secret"]).now()}).json()["access"]}
users = requests.get(B + "users/", headers=AH).json()
eid = next(u["id"] for u in users if u["username"] == "elmira")
r = requests.post(B + f"users/{eid}/reset-2fa/", headers=AH)
ok("админ сбросил 2FA руководителю", r.status_code == 200 and not r.json()["has_2fa"])
r = requests.post(B + "auth/login/", json=P)
ok("после сброса снова обязательная настройка", r.status_code == 403 and r.json().get("setup_required"))
ok("юрист не может сбрасывать 2FA", requests.post(B + f"users/{eid}/reset-2fa/", headers=LH).status_code == 403)

print("\nFAILS:", F)
