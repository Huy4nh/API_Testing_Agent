from __future__ import annotations

import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.settings import settings


def ensure_sessions_dir() -> None:
    os.makedirs(settings.sessions_dir, exist_ok=True)


def build_session_path(owner_id: int, label: str) -> str:
    ensure_sessions_dir()
    user_dir = os.path.join(settings.sessions_dir, str(owner_id))
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, label)


async def connect_bot_sender(owner_id: int, label: str, bot_token: str) -> tuple[str, str]:
    """
    Đăng nhập một bot sender bằng Telethon.
    Return:
        (session_key, display_name)
    """
    session_key = build_session_path(owner_id, label)
    client = TelegramClient(
        session=session_key,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
    )

    await client.start(bot_token=bot_token)
    try:
        me = await client.get_me()
        display_name = me.username or me.first_name or "bot"
        return session_key, display_name
    finally:
        await client.disconnect()


async def request_user_login_code(owner_id: int, label: str, phone: str) -> tuple[str, str]:
    """
    Gửi OTP tới user account.
    Return:
        (session_key, phone_code_hash)
    """
    session_key = build_session_path(owner_id, label)
    client = TelegramClient(
        session=session_key,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
    )

    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        return session_key, sent.phone_code_hash
    finally:
        await client.disconnect()


async def verify_user_otp(
    session_key: str,
    phone: str,
    otp: str,
    phone_code_hash: str,
) -> tuple[bool, str]:
    """
    Return:
        (need_2fa, display_name_or_message)
    """
    client = TelegramClient(
        session=session_key,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
    )

    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=phone,
                code=otp,
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            return True, "2FA_REQUIRED"

        me = await client.get_me()
        display_name = me.username or me.first_name or "user"
        return False, display_name
    finally:
        await client.disconnect()


async def verify_user_2fa(session_key: str, password: str) -> str:
    client = TelegramClient(
        session=session_key,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
    )

    await client.connect()
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        return me.username or me.first_name or "user"
    finally:
        await client.disconnect()