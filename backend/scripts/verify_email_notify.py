# -*- coding: utf-8 -*-
"""새 고객문의 알림(메일 + 슬랙) 회귀 검증 — DB·네트워크·실제 SMTP 불필요.

    py scripts/verify_email_notify.py

  (a) 메일이 꺼져 있으면(SMTP_HOST 없음) 아무것도 보내지 않고 False
  (b) 켜져 있으면 STARTTLS → 로그인 → 수신자에게 1통(465 는 SMTP_SSL)
  (c) 전송 실패는 예외 없이 False 이고, 로그에 비밀번호가 없다
  (d) 알림 본문에는 문의 내용·문의자 이메일이 들어갈 자리가 없다(번호·시각만)
  (e) 슬랙과 메일은 독립 — 한쪽이 실패해도 다른 쪽은 나간다
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services import email_notify, inquiry_notify, slack_notify  # noqa: E402

FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAIL.append(name)


def cfg(**kw):
    base = dict(smtp_host="smtp.test", smtp_port=587, smtp_user="bot@test", smtp_password="SECRET-PW-123",
                smtp_from="", inquiry_notify_to="sumeungil@googlegroups.com", slack_webhook_url="https://hooks.test/x")
    base.update(kw)
    return SimpleNamespace(**base)


class FakeSMTP:
    sent: list = []
    log: list = []
    boom = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        FakeSMTP.log.append(("connect", host, port))
        if FakeSMTP.boom:
            raise OSError("connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        FakeSMTP.log.append(("starttls",))

    def login(self, user, pw):
        FakeSMTP.log.append(("login", user))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def reset():
    FakeSMTP.sent, FakeSMTP.log, FakeSMTP.boom = [], [], False


email_notify.smtplib.SMTP = FakeSMTP
email_notify.smtplib.SMTP_SSL = FakeSMTP

print("\n[a] 꺼져 있을 때")
reset()
check("SMTP_HOST 없으면 is_enabled False", email_notify.is_enabled(cfg(smtp_host="")) is False)
r = asyncio.run(email_notify.send_text(cfg(smtp_host=""), "a@b.c", "s", "b"))
check("꺼져 있으면 False 이고 연결도 안 함", r is False and not FakeSMTP.log)

print("\n[b] 켜져 있을 때")
reset()
r = asyncio.run(email_notify.send_text(cfg(), "sumeungil@googlegroups.com", "제목", "본문"))
check("전송 성공 True", r is True)
check("STARTTLS 후 로그인", [x[0] for x in FakeSMTP.log] == ["connect", "starttls", "login"], str(FakeSMTP.log))
m = FakeSMTP.sent[0]
check("수신자·제목·발신자(SMTP_USER 대체)", m["To"] == "sumeungil@googlegroups.com" and m["Subject"] == "제목" and m["From"] == "bot@test")
reset()
asyncio.run(email_notify.send_text(cfg(smtp_port=465, smtp_from="noreply@test"), "x@y.z", "s", "b"))
check("465 는 암묵적 TLS(starttls 안 함)", ("starttls",) not in FakeSMTP.log and FakeSMTP.sent[0]["From"] == "noreply@test")

print("\n[c] 실패는 조용히")
reset()
FakeSMTP.boom = True
stream = io.StringIO()
handler = logging.StreamHandler(stream)
logging.getLogger("sumeungil.email_notify").addHandler(handler)
try:
    r = asyncio.run(email_notify.send_text(cfg(), "a@b.c", "s", "b"))
finally:
    logging.getLogger("sumeungil.email_notify").removeHandler(handler)
check("전송 실패해도 예외 없이 False", r is False)
check("로그에 비밀번호가 없다", "SECRET-PW-123" not in stream.getvalue(), stream.getvalue())

print("\n[d] 알림 내용")
subject, body = inquiry_notify.build_notice(42, "2026-09-20T21:30:00+09:00")
check("제목·본문에 번호와 시각", "#42" in subject and "#42" in body and "2026-09-20T21:30" in body)
check("문의 내용·이메일 주소가 들어갈 자리 없음", "@" not in body and "@" not in subject)

print("\n[e] 슬랙·메일 독립")
posted: list = []


async def fake_post(text, *, webhook_url):
    posted.append((text, webhook_url))
    return True


slack_notify.post = fake_post
reset()
out = asyncio.run(inquiry_notify.notify_new_inquiry(7, "2026-09-20T21:30:00+09:00", cfg()))
check("둘 다 성공", out == {"slack": True, "email": True} and len(FakeSMTP.sent) == 1 and len(posted) == 1, str(out))
check("슬랙 텍스트에 번호만(내용 없음)", "#7" in posted[0][0] and "@" not in posted[0][0])
reset(); posted.clear()
FakeSMTP.boom = True
out = asyncio.run(inquiry_notify.notify_new_inquiry(8, "t", cfg()))
check("메일이 실패해도 슬랙은 나간다", out == {"slack": True, "email": False}, str(out))
reset(); posted.clear()


async def failing_post(text, *, webhook_url):
    raise RuntimeError("slack down")


slack_notify.post = failing_post
out = asyncio.run(inquiry_notify.notify_new_inquiry(9, "t", cfg()))
check("슬랙이 예외를 내도 메일은 나가고 전체는 죽지 않는다", out["email"] is True and out["slack"] is False and len(FakeSMTP.sent) == 1, str(out))
out = asyncio.run(inquiry_notify.notify_new_inquiry(10, "t", cfg(smtp_host="", slack_webhook_url="")))
check("둘 다 꺼져 있으면 아무 일도 없이 둘 다 False", out == {"slack": False, "email": False}, str(out))

print(f"\n== {'ALL PASS' if not FAIL else 'FAIL'} ==", FAIL or "")
sys.exit(1 if FAIL else 0)
