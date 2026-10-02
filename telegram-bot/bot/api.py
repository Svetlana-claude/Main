"""Клиент Bot API — ровно то, что нужно боту, и ничего больше.

Своя обёртка вместо библиотеки: нужно семь методов, а `aiogram` тянет pydantic и
своё представление всех типов Телеграма. На сервере 2.9 ГБ ОЗУ и уже живёт
`webui`, поэтому здесь действует то же решение, что записано у него в
`architect.md` про Node.js и Docker, — лишний слой не оправдан.

Все тексты ошибок русские: они попадают в журнал службы, который читает человек.
"""
import asyncio
import json
import logging

import httpx

log = logging.getLogger("bot.api")

BASE = "https://api.telegram.org"

# Сколько ждать ответа. Чтение длинное: `getUpdates` висит до 60 с по нашей же
# просьбе, и обрывать его по таймауту нельзя.
TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=60.0, pool=10.0)

# Повторы при сетевом сбое и при 5xx: Телеграм иногда отвечает 502 на ровном месте
RETRIES = 4


class TelegramError(RuntimeError):
    """Телеграм ответил `ok: false`."""

    def __init__(self, method: str, code: int, description: str):
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description or ""

    @property
    def ne_izmeneno(self) -> bool:
        """Правка не изменила сообщения. Это не сбой: текст просто тот же."""
        return "message is not modified" in self.description

    @property
    def nedostupen(self) -> bool:
        """Собеседник закрыл бота или удалил сообщение — писать больше некуда."""
        return any(s in self.description for s in (
            "bot was blocked", "chat not found", "user is deactivated",
            "message to edit not found", "message to delete not found",
        ))


class Bot:
    def __init__(self, token: str):
        self._token = token
        self._client = httpx.AsyncClient(timeout=TIMEOUT)

    async def close(self) -> None:
        await self._client.aclose()

    # -- основной вызов ----------------------------------------------------

    async def call(self, method: str, *, files: dict | None = None, **params):
        """Вызов метода API. Возвращает `result`, при `ok: false` бросает TelegramError."""
        url = f"{BASE}/bot{self._token}/{method}"
        data = {}
        for key, value in params.items():
            if value is None:
                continue
            # Вложенные структуры (reply_markup, allowed_updates) уходят строкой JSON
            data[key] = json.dumps(value, ensure_ascii=False) if isinstance(
                value, (dict, list)) else value

        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                response = await self._client.post(url, data=data, files=files)
            except httpx.HTTPError as error:
                last = error
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            try:
                payload = response.json()
            except ValueError:
                last = RuntimeError(f"{method}: ответ не JSON ({response.status_code})")
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            if payload.get("ok"):
                return payload.get("result")

            description = str(payload.get("description") or "")
            pause = (payload.get("parameters") or {}).get("retry_after")

            # 429: Телеграм сам говорит, сколько ждать. Это штатный ответ, а не сбой,
            # и ждать надо именно столько — свой запас даёт отбой вторым кругом.
            if pause:
                log.warning("%s: отбой по частоте, ждём %s с", method, pause)
                await asyncio.sleep(float(pause) + 0.5)
                continue

            if response.status_code >= 500:
                last = TelegramError(method, response.status_code, description)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            raise TelegramError(method, response.status_code, description)

        raise last or RuntimeError(f"{method}: не удалось выполнить запрос")

    # -- то, чем бот пользуется -------------------------------------------

    async def get_updates(self, offset: int | None, timeout: int = 55) -> list[dict]:
        return await self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            # Правленые сообщения не берём: правка уже отвеченного — это новая
            # просьба, и пусть она будет новым сообщением, а не тихой подменой
            allowed_updates=["message", "callback_query"],
        ) or []

    async def send(
        self,
        chat_id: int,
        text: str,
        *,
        html: bool = False,
        markup: dict | None = None,
        reply_to: int | None = None,
        tiho: bool = False,
    ) -> dict:
        return await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML" if html else None,
            reply_markup=markup,
            reply_to_message_id=reply_to,
            disable_notification=tiho or None,
            link_preview_options={"is_disabled": True},
        )

    async def edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        html: bool = False,
        markup: dict | None = None,
    ) -> bool:
        """Правка сообщения. «Текст тот же» и «сообщения нет» — не сбой, а ответ «нет»."""
        try:
            await self.call(
                "editMessageText",
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML" if html else None,
                reply_markup=markup,
                link_preview_options={"is_disabled": True},
            )
            return True
        except TelegramError as error:
            if error.ne_izmeneno or error.nedostupen:
                return False
            raise

    async def edit_markup(self, chat_id: int, message_id: int, markup: dict | None) -> bool:
        """Снять или заменить кнопки, не трогая текст."""
        try:
            await self.call(
                "editMessageReplyMarkup",
                chat_id=chat_id, message_id=message_id, reply_markup=markup,
            )
            return True
        except TelegramError as error:
            if error.ne_izmeneno or error.nedostupen:
                return False
            raise

    async def delete(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TelegramError as error:
            if not error.nedostupen:
                raise

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Погасить «часики» на нажатой кнопке. Без этого она крутится до минуты."""
        try:
            await self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except TelegramError:
            pass     # запрос мог устареть — показывать это некому

    async def action(self, chat_id: int, name: str = "typing") -> None:
        """«Печатает…». Живёт 5 с, поэтому повторяется по ходу длинного ответа."""
        try:
            await self.call("sendChatAction", chat_id=chat_id, action=name)
        except TelegramError:
            pass

    async def send_document(
        self, chat_id: int, name: str, data: bytes, caption: str = ""
    ) -> dict:
        return await self.call(
            "sendDocument",
            chat_id=chat_id,
            caption=caption or None,
            parse_mode="HTML" if caption else None,
            files={"document": (name, data)},
        )

    async def download(self, file_id: str) -> tuple[str, bytes]:
        """Забрать присланный файл. Возвращает путь на стороне Телеграма и содержимое."""
        info = await self.call("getFile", file_id=file_id)
        path = info["file_path"]
        url = f"{BASE}/file/bot{self._token}/{path}"
        response = await self._client.get(url)
        response.raise_for_status()
        return path, response.content

    async def set_commands(self, commands: list[tuple[str, str]]) -> None:
        await self.call(
            "setMyCommands",
            commands=[{"command": name, "description": text} for name, text in commands],
        )

    async def me(self) -> dict:
        return await self.call("getMe")


def knopki(rows: list[list[tuple[str, str]]]) -> dict:
    """Клавиатура под сообщением: строки из пар (надпись, данные нажатия)."""
    return {"inline_keyboard": [
        [{"text": text, "callback_data": data} for text, data in row] for row in rows
    ]}
