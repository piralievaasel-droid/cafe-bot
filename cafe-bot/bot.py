from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import asyncio
import logging

from config import BOT_TOKEN, ADMIN_IDS, SHEET_KEY, SERVICE_ACCOUNT_FILE

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# ---------------------- Безопасное преобразование чисел ----------------------
def safe_float(value, default=0.0):
    """Преобразует в float, автоматически заменяя запятую на точку."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except (ValueError, TypeError):
        return default

# ---------------------- Google Sheets ----------------------
def connect_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_KEY)
    return sheet

def get_worksheet(sheet, name):
    return sheet.worksheet(name)

def get_all_rows(ws):
    return ws.get_all_records(expected_headers=[])

def append_row(ws, row):
    ws.append_row(row, value_input_option='USER_ENTERED')

def update_cell(ws, row, col, value):
    ws.update_cell(row, col, value)

# ---------------------- Состояния FSM ----------------------
class SpendProduct(StatesGroup):
    waiting_for_category = State()
    waiting_for_product = State()
    waiting_for_quantity = State()

class ReceiveGoods(StatesGroup):
    waiting_for_order_selection = State()
    waiting_for_actual_quantity = State()

# ---------------------- Инициализация бота и диспетчера ----------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------------- Клавиатуры ----------------------
def employee_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Списать продукт"))
    builder.add(KeyboardButton(text="Последние 5 списаний"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def admin_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Списать продукт"))
    builder.add(KeyboardButton(text="Последние 5 списаний"))
    builder.add(KeyboardButton(text="Активные заказы на пополнение"))
    builder.add(KeyboardButton(text="Принять поступление"))
    builder.add(KeyboardButton(text="История пополнений"))
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

# ---------------------- /start ----------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id in ADMIN_IDS:
        await message.answer("Добро пожаловать, администратор!", reply_markup=admin_main_kb())
    else:
        await message.answer("Добро пожаловать! Вы вошли как сотрудник.", reply_markup=employee_main_kb())

# ====================== СОТРУДНИК ======================
@dp.message(F.text == "Списать продукт")
async def spend_start(message: types.Message, state: FSMContext):
    sheet = connect_sheets()
    try:
        ws_stock = get_worksheet(sheet, "Остатки")
        records = get_all_rows(ws_stock)
        categories = list({r["Категория"] for r in records if r["Категория"]})
        if not categories:
            await message.answer("Нет доступных продуктов.")
            return
        builder = InlineKeyboardBuilder()
        for cat in sorted(categories):
            builder.add(InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))
        builder.adjust(2)
        await message.answer("Выберите категорию:", reply_markup=builder.as_markup())
        await state.set_state(SpendProduct.waiting_for_product)
    except Exception as e:
        logging.error(e)
        await message.answer("Ошибка при загрузке данных.")

@dp.callback_query(F.data.startswith("cat_"), SpendProduct.waiting_for_product)
async def choose_category(call: types.CallbackQuery, state: FSMContext):
    category = call.data[4:]
    sheet = connect_sheets()
    ws_stock = get_worksheet(sheet, "Остатки")
    all_records = get_all_rows(ws_stock)
    # ИСПРАВЛЕНО: safe_float
    products = [r for r in all_records if r["Категория"] == category and safe_float(r["Текущий_остаток"]) > 0]
    if not products:
        await call.message.edit_text("В этой категории нет доступных продуктов.", reply_markup=None)
        await state.clear()
        return
    builder = InlineKeyboardBuilder()
    for p in products:
        builder.add(InlineKeyboardButton(
            text=f"{p['Наименование']} ({p['Текущий_остаток']} {p['Единица_изм']})",
            callback_data=f"prod_{p['ID_продукта']}"
        ))
    builder.adjust(1)
    await call.message.edit_text("Выберите продукт:", reply_markup=builder.as_markup())
    await state.update_data(products=products)
    await state.set_state(SpendProduct.waiting_for_quantity)

@dp.callback_query(F.data.startswith("prod_"), SpendProduct.waiting_for_quantity)
async def choose_product(call: types.CallbackQuery, state: FSMContext):
    product_id = int(call.data[5:])
    await state.update_data(chosen_product_id=product_id)
    data = await state.get_data()
    products = data.get("products", [])
    product = next((p for p in products if int(p["ID_продукта"]) == product_id), None)
    if not product:
        await call.message.edit_text("Продукт не найден, попробуйте снова.")
        await state.clear()
        return
    # ИСПРАВЛЕНО: safe_float
    current_stock = safe_float(product["Текущий_остаток"])
    await call.message.edit_text(
        f"Продукт: {product['Наименование']}\nТекущий остаток: {current_stock} {product['Единица_изм']}\n\nВведите количество для списания (число):"
    )
    await state.set_state(SpendProduct.waiting_for_quantity)

@dp.message(SpendProduct.waiting_for_quantity)
async def process_spend_quantity(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Пожалуйста, введите число.")
        return
    if qty <= 0:
        await message.answer("Количество должно быть положительным.")
        return

    data = await state.get_data()
    prod_id = data["chosen_product_id"]
    username = message.from_user.username or message.from_user.first_name

    sheet = connect_sheets()
    ws_stock = get_worksheet(sheet, "Остатки")
    ws_expense = get_worksheet(sheet, "Расход")
    ws_orders = get_worksheet(sheet, "Требуется_заказ")

    stock_values = ws_stock.get_all_values()
    header = stock_values[0]
    id_col = header.index("ID_продукта") + 1
    name_col = header.index("Наименование") + 1
    stock_col = header.index("Текущий_остаток") + 1
    min_col = header.index("Минимальный_запас") + 1
    unit_col = header.index("Единица_изм") + 1

    target_row = None
    for row_idx, row in enumerate(stock_values[1:], start=2):
        if int(row[id_col-1]) == prod_id:
            target_row = row_idx
            # ИСПРАВЛЕНО: safe_float
            current_stock = safe_float(row[stock_col-1])
            product_name = row[name_col-1]
            min_stock = safe_float(row[min_col-1])
            unit = row[unit_col-1]
            break

    if target_row is None:
        await message.answer("Продукт не найден в таблице остатков.")
        await state.clear()
        return

    if qty > current_stock:
        await message.answer(f"Недостаточно остатка. Доступно: {current_stock} {unit}. Повторите ввод.")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expense_row = [now, f"@{username}", prod_id, qty, ""]
    append_row(ws_expense, expense_row)

    new_stock = current_stock - qty
    update_cell(ws_stock, target_row, stock_col, new_stock)

    await message.answer(f"Списано: {product_name}, {qty} {unit}. Остаток: {new_stock:.2f} {unit}")

    if new_stock < min_stock:
        required_qty = round(1.5 * min_stock - new_stock, 2)
        # Использовать существующие ID заказов или начать с 1
        existing_ids = [int(r["ID_заказа"]) for r in get_all_rows(ws_orders) if str(r["ID_заказа"]).isdigit()]
        order_id = max(existing_ids) + 1 if existing_ids else 1
        order_row = [order_id, datetime.now().strftime("%Y-%m-%d"), prod_id, required_qty, "Требуется заказ", ""]
        append_row(ws_orders, order_row)

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🛑 Внимание: {product_name} ниже мин. остатка ({min_stock} {unit}).\n"
                    f"Текущий остаток: {new_stock:.2f} {unit}.\n"
                    f"Создана заявка на заказ {required_qty} {unit}."
                )
            except Exception as e:
                logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    await state.clear()

# --- Последние 5 списаний сотрудника ---
@dp.message(F.text == "Последние 5 списаний")
async def last_spends(message: types.Message):
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    sheet = connect_sheets()
    ws_expense = get_worksheet(sheet, "Расход")
    all_values = ws_expense.get_all_values()
    if len(all_values) <= 1:
        await message.answer("Нет записей о списаниях.")
        return
    rows = []
    for row in reversed(all_values[1:]):
        if row[1] == username:
            rows.append(row)
            if len(rows) == 5:
                break
    if not rows:
        await message.answer("У вас нет списаний.")
        return
    output = "Ваши последние списания:\n"
    for r in rows:
        output += f"{r[0]} — ID продукта {r[2]}, {r[3]} шт/кг\n"
    await message.answer(output)

# ====================== АДМИНИСТРАТОР ======================
@dp.message(F.text == "Активные заказы на пополнение")
async def admin_active_orders(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    sheet = connect_sheets()
    ws_orders = get_worksheet(sheet, "Требуется_заказ")
    records = get_all_rows(ws_orders)
    active = [r for r in records if r["Статус"] == "Требуется заказ"]
    if not active:
        await message.answer("Нет активных заказов.")
        return

    ws_stock = get_worksheet(sheet, "Остатки")
    stock_records = get_all_rows(ws_stock)
    for order in active:
        product = next((p for p in stock_records if int(p["ID_продукта"]) == int(order["ID_продукта"])), None)
        product_name = product["Наименование"] if product else f"ID {order['ID_продукта']}"
        unit = product["Единица_изм"] if product else "ед."
        text = f"Заказ №{order['ID_заказа']}\nПродукт: {product_name}\nТребуется: {order['Требуемое_количество']} {unit}"
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅ Заказано", callback_data=f"order_status_{order['ID_заказа']}_ordered"))
        builder.add(InlineKeyboardButton(text="❌ Отменить", callback_data=f"order_status_{order['ID_заказа']}_cancelled"))
        await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("order_status_"))
async def change_order_status(call: types.CallbackQuery):
    parts = call.data.split("_")
    order_id = parts[2]
    new_status = "Заказано" if parts[3] == "ordered" else "Отменено"
    sheet = connect_sheets()
    ws_orders = get_worksheet(sheet, "Требуется_заказ")
    all_vals = ws_orders.get_all_values()
    target_row = None
    for idx, row in enumerate(all_vals[1:], start=2):
        if row[0] == order_id:
            target_row = idx
            break
    if target_row:
        update_cell(ws_orders, target_row, 5, new_status)
        if new_status == "Заказано":
            admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
            update_cell(ws_orders, target_row, 6, admin_name)
        await call.message.edit_text(f"Статус заказа №{order_id} изменён на «{new_status}».")
    else:
        await call.message.edit_text("Заказ не найден, возможно, уже обработан.")
    await call.answer()

@dp.message(F.text == "Принять поступление")
async def receive_goods_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    sheet = connect_sheets()
    ws_orders = get_worksheet(sheet, "Требуется_заказ")
    records = get_all_rows(ws_orders)
    ordered = [r for r in records if r["Статус"] == "Заказано"]
    if not ordered:
        await message.answer("Нет заказов в статусе «Заказано» для приёмки.")
        return

    builder = InlineKeyboardBuilder()
    for o in ordered:
        builder.add(InlineKeyboardButton(
            text=f"Заказ №{o['ID_заказа']} (продукт {o['ID_продукта']}, {o['Требуемое_количество']})",
            callback_data=f"receive_{o['ID_заказа']}"
        ))
    builder.adjust(1)
    await message.answer("Выберите заказ для приёмки:", reply_markup=builder.as_markup())
    await state.set_state(ReceiveGoods.waiting_for_order_selection)

@dp.callback_query(F.data.startswith("receive_"), ReceiveGoods.waiting_for_order_selection)
async def select_receive_order(call: types.CallbackQuery, state: FSMContext):
    order_id = call.data[8:]
    await state.update_data(receive_order_id=order_id)
    await call.message.edit_text("Введите фактическое количество поступившего товара (число):")
    await state.set_state(ReceiveGoods.waiting_for_actual_quantity)

@dp.message(ReceiveGoods.waiting_for_actual_quantity)
async def process_receive_quantity(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите число.")
        return
    if qty <= 0:
        await message.answer("Количество должно быть положительным.")
        return

    data = await state.get_data()
    order_id = data["receive_order_id"]
    username = message.from_user.username or message.from_user.first_name

    sheet = connect_sheets()
    ws_orders = get_worksheet(sheet, "Требуется_заказ")
    ws_stock = get_worksheet(sheet, "Остатки")
    ws_log = get_worksheet(sheet, "Лог_пополнений")

    all_vals = ws_orders.get_all_values()
    target_row = None
    product_id = None
    for idx, row in enumerate(all_vals[1:], start=2):
        if row[0] == order_id:
            target_row = idx
            product_id = int(row[2])
            break
    if target_row is None:
        await message.answer("Заказ не найден.")
        await state.clear()
        return

    update_cell(ws_orders, target_row, 5, "Получено")

    now = datetime.now().strftime("%Y-%m-%d")
    log_row = [now, product_id, qty, f"@{username}"]
    append_row(ws_log, log_row)

    stock_values = ws_stock.get_all_values()
    header = stock_values[0]
    id_col = header.index("ID_продукта") + 1
    stock_col = header.index("Текущий_остаток") + 1

    for r_idx, row in enumerate(stock_values[1:], start=2):
        if int(row[id_col-1]) == product_id:
            # ИСПРАВЛЕНО: safe_float
            current_stock = safe_float(row[stock_col-1])
            new_stock = current_stock + qty
            update_cell(ws_stock, r_idx, stock_col, new_stock)
            break

    await message.answer(f"Склад обновлён. Продукт ID {product_id} пополнен на {qty}.")
    await state.clear()

@dp.message(F.text == "История пополнений")
async def history_receipts(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    sheet = connect_sheets()
    ws_log = get_worksheet(sheet, "Лог_пополнений")
    vals = ws_log.get_all_values()
    if len(vals) <= 1:
        await message.answer("История пуста.")
        return
    recent = vals[-11:-1] if len(vals) > 11 else vals[1:]
    out = "Последние поступления:\n"
    for r in recent:
        out += f"{r[0]} — продукт {r[1]}, {r[2]} ед., подтв. {r[3]}\n"
    await message.answer(out)

# ---------------------- Запуск ----------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())