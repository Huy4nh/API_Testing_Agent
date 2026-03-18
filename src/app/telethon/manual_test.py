import asyncio
from app.settings import settings
from app.telethon.service import connect_bot_sender


async def run() -> None:
    owner_id = 1
    label = "bot1"
    bot_token=settings.bot_token

    session_key, display_name = await connect_bot_sender(
        owner_id=owner_id,
        label=label,
        bot_token=bot_token,
    )
    print("Connected:", display_name)
    print("Session:", session_key)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()