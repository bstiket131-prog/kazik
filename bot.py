import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ (ДАННЫЕ ВНЕСЕНЫ)
# ---------------------------------------------------------------------------
BOT_TOKEN = ""
SUPER_ADMIN_ID = 7838553850

DB_NAME = "bot_settings.db"
logging.basicConfig(level=logging.INFO)

class AdminStates(StatesGroup):
    change_chance = State()
    change_text = State()
    add_admin = State()
    change_photo = State()

# ---------------------------------------------------------------------------
# БД И МИГРАЦИЯ
# ---------------------------------------------------------------------------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY DEFAULT 1,
                chance REAL DEFAULT 50.0,
                reply_text TEXT DEFAULT 'Привет!',
                is_active INTEGER DEFAULT 1,
                photo_id TEXT DEFAULT NULL,
                pin_enabled INTEGER DEFAULT 0
            )
        """)
        
        columns = [("photo_id", "TEXT"), ("pin_enabled", "INTEGER DEFAULT 0")]
        for col_name, col_type in columns:
            try:
                await db.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}")
            except: pass 
            
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        await db.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.commit()

async def is_admin(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as c:
            return await c.fetchone() is not None

async def get_settings():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id = 1") as cursor:
            return await cursor.fetchone()

# ---------------------------------------------------------------------------
# КЛАВИАТУРА АДМИН-ПАНЕЛИ
# ---------------------------------------------------------------------------
async def get_admin_keyboard():
    s = await get_settings()
    builder = InlineKeyboardBuilder()
    
    chance_val = s['chance']
    chance_str = f"{chance_val:g}" if chance_val is not None else "50"
    
    builder.button(text=f"🎲 Шанс: {chance_str}%", callback_data="set_chance")
    builder.button(text="📝 Текст", callback_data="set_text")
    
    photo_status = "✅ Фото есть" if s['photo_id'] else "❌ Без фото"
    builder.button(text=f"🖼 {photo_status}", callback_data="set_photo")
    if s['photo_id']:
        builder.button(text="🗑 Удалить фото", callback_data="del_photo")
    
    pin_status = "📌 Закреп: ВКЛ" if s['pin_enabled'] else "📌 Закреп: ВЫКЛ"
    builder.button(text=pin_status, callback_data="toggle_pin")
    
    bot_status = "🟢 Включен" if s['is_active'] else "🔴 Выключен"
    builder.button(text=bot_status, callback_data="toggle_status")
    
    builder.button(text="👤 +Админ", callback_data="add_admin")
    builder.button(text="❌ Закрыть", callback_data="close_menu")
    builder.adjust(2, 2, 1, 1, 2)
    return builder.as_markup()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------------------------------------------------------------------
# ХЕНДЛЕРЫ АДМИНКИ
# ---------------------------------------------------------------------------
@dp.message(Command("admin"), F.chat.type == "private")
async def cmd_admin(message: types.Message):
    if await is_admin(message.from_user.id):
        await message.answer("Управление автоответчиком:", reply_markup=await get_admin_keyboard())

@dp.callback_query(F.data == "toggle_pin")
async def cb_pin(call: types.CallbackQuery):
    s = await get_settings()
    new_val = 0 if s['pin_enabled'] else 1
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET pin_enabled = ? WHERE id = 1", (new_val,))
        await db.commit()
    await call.message.edit_reply_markup(reply_markup=await get_admin_keyboard())
    await call.answer()

@dp.callback_query(F.data == "set_photo")
async def cb_photo(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Отправьте фото, которое бот будет использовать в ответах:")
    await state.set_state(AdminStates.change_photo)
    await call.answer()

@dp.message(AdminStates.change_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET photo_id = ? WHERE id = 1", (file_id,))
        await db.commit()
    await state.clear()
    await message.answer("✅ Фото успешно сохранено!", reply_markup=await get_admin_keyboard())

@dp.callback_query(F.data == "del_photo")
async def cb_del_photo(call: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET photo_id = NULL WHERE id = 1")
        await db.commit()
    await call.message.edit_reply_markup(reply_markup=await get_admin_keyboard())
    await call.answer("Фото удалено, теперь только текст.")

@dp.callback_query(F.data == "toggle_status")
async def cb_status(call: types.CallbackQuery):
    s = await get_settings()
    new_status = 0 if s['is_active'] else 1
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET is_active = ? WHERE id = 1", (new_status,))
        await db.commit()
    await call.message.edit_reply_markup(reply_markup=await get_admin_keyboard())
    await call.answer()

@dp.callback_query(F.data == "set_chance")
async def cb_chance(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите шанс (от 0 до 100, можно дробное число через точку, например 0.1):")
    await state.set_state(AdminStates.change_chance)
    await call.answer()

@dp.message(AdminStates.change_chance)
async def p_chance(m: types.Message, state: FSMContext):
    raw_text = m.text.replace(",", ".")
    try:
        chance = float(raw_text)
        if 0.0 <= chance <= 100.0:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("UPDATE settings SET chance = ? WHERE id = 1", (chance,))
                await db.commit()
            await state.clear()
            await m.answer(f"✅ Шанс изменен на: {chance:g}%", reply_markup=await get_admin_keyboard())
        else:
            await m.answer("Число должно быть в диапазоне от 0 до 100.")
    except ValueError:
        await m.answer("Пожалуйста, введите корректное число (например: 0.5 или 12).")

@dp.callback_query(F.data == "set_text")
async def cb_text(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Введите текст ответа:")
    await state.set_state(AdminStates.change_text)
    await call.answer()

@dp.message(AdminStates.change_text)
async def p_text(m: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET reply_text = ? WHERE id = 1", (m.text,))
        await db.commit()
    await state.clear()
    await m.answer("✅ Текст изменен", reply_markup=await get_admin_keyboard())

@dp.callback_query(F.data == "close_menu")
async def cb_close(call: types.CallbackQuery):
    await call.message.delete()

# ---------------------------------------------------------------------------
# ГЛАВНАЯ ЛОГИКА (ОТВЕТЫ РЕПЛАЕМ)
# ---------------------------------------------------------------------------
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_handler(message: types.Message):
    s = await get_settings()
    if not s['is_active']: return
    
    if random.uniform(0.0, 100.0) <= s['chance']:
        try:
            if s['photo_id']:
                res = await message.reply_photo(photo=s['photo_id'], caption=s['reply_text'])
            else:
                res = await message.reply(text=s['reply_text'])
            
            if s['pin_enabled']:
                await res.pin(disable_notification=True)
        except Exception as e:
            logging.error(f"Ошибка при ответе: {e}")

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
