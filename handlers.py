import asyncio
import re
from datetime import datetime, time, timedelta
from typing import Dict, List, Tuple, Optional

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import bot
from config import ADMIN_ID, DELTA
from database import add_chat, remove_chat, get_all_chats

router = Router()

# Хранилище данных
active_timer = None


class TimerStates(StatesGroup):
    pre_text = State()
    post_text = State()
    end_time = State()
    button_names = State()
    button_urls = State()


class ChatManagementStates(StatesGroup):
    waiting_for_add_chat = State()
    waiting_for_remove_chat = State()


class TimerData:
    def __init__(
            self,
            pre_text: str,
            post_text: str,
            end_time: time,
            button_names: List[str],
            button_urls: List[str],
    ):
        self.pre_text = pre_text
        self.post_text = post_text
        self.end_time = end_time
        self.button_names = button_names
        self.button_urls = button_urls
        self.chat_messages: Dict[str, int] = {}
        self.task: Optional[asyncio.Task] = None
        self.active = True
        self.locks: Dict[str, asyncio.Lock] = {}  # Блокировки для каждого чата


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def format_duration(seconds: int) -> str:
    """Форматирует время в формат: X HOURS Y MINUTES"""
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    parts = []
    if hours > 0:
        parts.append(f"{hours} HOUR{'S' if hours != 1 else ''}")
    parts.append(f"{minutes} MINUTE{'S' if minutes != 1 else ''}")
    formatted = ' '.join(parts)

    return f"<b>{formatted}</b>"


async def update_timer(timer_data: TimerData):
    while timer_data.active:
        now = datetime.now() + timedelta(hours=DELTA)
        end_datetime = datetime.combine(now.date(), timer_data.end_time)

        if end_datetime <= now:
            end_datetime += timedelta(days=1)

        remaining = end_datetime - now

        # Остановка за 1 минуту до конца
        if remaining <= timedelta(minutes=1):
            timer_data.active = False
            break

        # Форматирование времени
        total_seconds = int(remaining.total_seconds())
        formatted_time = format_duration(total_seconds)
        timer_text = f"{timer_data.pre_text}\n{formatted_time}\n{timer_data.post_text}"

        # Создание клавиатуры - каждая кнопка в отдельный ряд
        builder = InlineKeyboardBuilder()
        for name, url in zip(timer_data.button_names, timer_data.button_urls):
            builder.row(InlineKeyboardButton(text=name, url=url))
        keyboard = builder.as_markup()

        # Обновление сообщений во всех чатах
        for chat_id in list(timer_data.chat_messages.keys()):
            # Создаем блокировку для чата, если ее нет
            if chat_id not in timer_data.locks:
                timer_data.locks[chat_id] = asyncio.Lock()

            async with timer_data.locks[chat_id]:
                try:

                    print(f'Удаляем старое сообщение в чате {chat_id}')
                    await bot.delete_message(chat_id=chat_id, message_id=timer_data.chat_messages[chat_id])
                    print('Удалено')
                except Exception as e:
                    print(f'Сообщение не удалено в {chat_id}')
                    print(str(e))
                    # Если сообщение не найдено, продолжаем
                    if "message to delete not found" not in str(e).lower():
                        print(f"Ошибка при удалении сообщения в {chat_id}: {e}")
                        continue

                try:
                    print(f'Отправляем новое сообщение в чате {chat_id}')
                    # Отправляем новое сообщение
                    new_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=timer_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    print('Отправлено')
                    timer_data.chat_messages[chat_id] = new_msg.message_id
                except Exception as e:
                    print(f"Ошибка при отправке сообщения в {chat_id}: {e}")
                    # Если бота исключили из чата, удаляем чат из списка
                    if "chat not found" in str(e).lower() or "bot was kicked" in str(e).lower():
                        timer_data.chat_messages.pop(chat_id, None)

        await asyncio.sleep(10)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "👮‍♂️ Таймер-бот\n\n"
        "Доступные команды:\n"
        "/add - запустить новый таймер\n"
        "/add_chat - добавить чат\n"
        "/remove_chat - удалить чат\n"
        "/get_chats - все чаты\n"
        "/stop - остановить таймер"
    )


@router.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(TimerStates.pre_text)
    await message.answer("Введите текст ДО таймера:")


@router.message(TimerStates.pre_text)
async def process_pre_text(message: types.Message, state: FSMContext):
    await state.update_data(pre_text=message.text)
    await state.set_state(TimerStates.post_text)
    await message.answer("Введите текст ПОСЛЕ таймера:")


@router.message(TimerStates.post_text)
async def process_post_text(message: types.Message, state: FSMContext):
    await state.update_data(post_text=message.text)
    await state.set_state(TimerStates.end_time)
    await message.answer("Введите время окончания (HH:MM по UTC):")


@router.message(TimerStates.end_time)
async def process_end_time(message: types.Message, state: FSMContext):
    time_match = re.match(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$', message.text)
    if not time_match:
        await message.answer("Некорректный формат времени. Используйте HH:MM")
        return

    hours, minutes = map(int, time_match.groups())
    end_time = time(hour=hours, minute=minutes)
    await state.update_data(end_time=end_time)
    await state.set_state(TimerStates.button_names)
    await message.answer("Введите названия кнопок через запятую (3 кнопки):")


@router.message(TimerStates.button_names)
async def process_button_names(message: types.Message, state: FSMContext):
    names = [name.strip() for name in message.text.split(',')]
    if len(names) != 3:
        await message.answer("Нужно ровно 3 названия через запятую!")
        return

    await state.update_data(button_names=names)
    await state.set_state(TimerStates.button_urls)
    await message.answer("Введите ссылки для кнопок через запятую (3 ссылки):")


@router.message(TimerStates.button_urls)
async def process_button_urls(message: types.Message, state: FSMContext):
    global active_timer

    urls = [url.strip() for url in message.text.split(',')]
    if len(urls) != 3:
        await message.answer("Нужно ровно 3 ссылки через запятую!")
        return

    data = await state.get_data()
    await state.clear()

    # Останавливаем предыдущий таймер
    if active_timer:
        active_timer.active = False
        if active_timer.task:
            active_timer.task.cancel()

    # Создаем новый таймер
    active_timer = TimerData(
        pre_text=data['pre_text'],
        post_text=data['post_text'],
        end_time=data['end_time'],
        button_names=data['button_names'],
        button_urls=urls
    )

    # Отправляем сообщения во все активные чаты из БД
    for chat_id in get_all_chats():
        try:
            now = datetime.now() + timedelta(hours=DELTA)
            end_datetime = datetime.combine(now.date(), active_timer.end_time)
            if end_datetime <= now:
                end_datetime += timedelta(days=1)

            remaining = end_datetime - now
            total_seconds = int(remaining.total_seconds())
            formatted_time = format_duration(total_seconds)
            timer_text = f"{active_timer.pre_text}\n{formatted_time}\n{active_timer.post_text}"

            # Кнопки в отдельных рядах
            builder = InlineKeyboardBuilder()
            for name, url in zip(active_timer.button_names, active_timer.button_urls):
                builder.row(InlineKeyboardButton(text=name, url=url))
            keyboard = builder.as_markup()

            msg = await bot.send_message(
                chat_id=chat_id,
                text=timer_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            active_timer.chat_messages[chat_id] = msg.message_id
        except Exception as e:
            print(f"Ошибка при отправке в {chat_id}: {e}")

    # Запускаем задачу обновления
    active_timer.task = asyncio.create_task(update_timer(active_timer))
    await message.answer("✅ Таймер запущен во всех активных чатах!")


# Команды для управления чатами с использованием FSM
@router.message(Command("add_chat"))
async def cmd_add_chat(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(ChatManagementStates.waiting_for_add_chat)
    await message.answer("Отправьте ID чата в формате: -100xxxxxxxxxx")


@router.message(ChatManagementStates.waiting_for_add_chat, F.text.regexp(r'^-100\d+$'))
async def process_add_chat(message: types.Message, state: FSMContext):
    chat_id = message.text.strip()
    add_chat(chat_id)
    await state.clear()
    await message.answer(f"✅ Чат {chat_id} добавлен!")


@router.message(Command("remove_chat"))
async def cmd_remove_chat(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(ChatManagementStates.waiting_for_remove_chat)
    await message.answer("Отправьте ID чата для удаления:")


@router.message(ChatManagementStates.waiting_for_remove_chat, F.text.regexp(r'^-100\d+$'))
async def process_remove_chat(message: types.Message, state: FSMContext):
    chat_id = message.text.strip()
    remove_chat(chat_id)
    await state.clear()
    await message.answer(f"❌ Чат {chat_id} удален!")


@router.message(Command("stop"))
async def cmd_stop(message: types.Message):
    global active_timer
    if not is_admin(message.from_user.id):
        return

    if active_timer:
        active_timer.active = False
        if active_timer.task:
            active_timer.task.cancel()
        active_timer = None
        await message.answer("⏹ Таймер остановлен!")
    else:
        await message.answer("Нет активных таймеров.")


@router.message(Command("get_chats"))
async def get_chats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    text = []
    for chat in get_all_chats():
        text.append(chat)
    if not text:
        text = ['Нет активных чатов!']
    await message.answer('\n'.join(text))
