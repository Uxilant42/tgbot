import logging
import sqlite3
import json
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота
BOT_TOKEN = "8462610940:AAGGiZC5iBq4RFz5-Ubp5cKsFVHOgRew3VY"  # ← ВСТАВЬ СЮДА СВОЙ ТОКЕН!

# Состояния
WAITING_SALARY, MAIN_MENU, WAITING_AMOUNT, WAITING_CATEGORY = range(4)

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('finance_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            salary REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            category TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_main_menu():
    """Создание главного меню с кнопками"""
    keyboard = [
        [KeyboardButton("💸 Ввести трату/пополнение")],
        [KeyboardButton("📊 Топ трат")],
        [KeyboardButton("📈 Средний расход")],
        [KeyboardButton("⏰ Когда кончатся деньги")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - начало работы"""
    await update.message.reply_text(
        "👋 Привет! Я ваш менеджер по финансам.\n\n"
        "💰 Введите вашу зарплату за месяц:"
    )
    return WAITING_SALARY

async def receive_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенной зарплаты"""
    try:
        salary = float(update.message.text)
        
        if salary <= 0:
            await update.message.reply_text("⚠️ Зарплата должна быть больше нуля. Попробуйте еще раз:")
            return WAITING_SALARY
        
        # Сохраняем в БД
        conn = sqlite3.connect('finance_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO users (user_id, salary) VALUES (?, ?)', 
            (update.effective_user.id, salary)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ Отлично! Ваша зарплата: {salary:.2f} руб.\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu()
        )
        return MAIN_MENU
        
    except ValueError:
        await update.message.reply_text("⚠️ Пожалуйста, введите число. Попробуйте еще раз:")
        return WAITING_SALARY

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления траты/пополнения"""
    await update.message.reply_text(
        "💰 Введите сумму:\n"
        "• Положительное число для траты (например: 500)\n"
        "• Отрицательное число для пополнения (например: -1000)"
    )
    return WAITING_AMOUNT

async def process_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенной суммы"""
    try:
        amount = float(update.message.text)
        context.user_data['temp_amount'] = amount
        await update.message.reply_text("📝 Введите категорию (на что потратили/откуда пополнение):")
        return WAITING_CATEGORY
    except ValueError:
        await update.message.reply_text("⚠️ Пожалуйста, введите число. Попробуйте еще раз:")
        return WAITING_AMOUNT

async def process_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка категории и сохранение в БД"""
    category = update.message.text
    amount = context.user_data.get('temp_amount')
    
    # Сохраняем в БД
    conn = sqlite3.connect('finance_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO expenses (user_id, amount, category) VALUES (?, ?, ?)', 
        (update.effective_user.id, amount, category)
    )
    conn.commit()
    conn.close()
    
    if amount > 0:
        await update.message.reply_text(
            f"✅ Трата добавлена:\n💸 {amount:.2f} руб. - {category}",
            reply_markup=get_main_menu()
        )
    else:
        await update.message.reply_text(
            f"✅ Пополнение добавлено:\n💰 {abs(amount):.2f} руб. - {category}",
            reply_markup=get_main_menu()
        )
    
    context.user_data.pop('temp_amount', None)
    return MAIN_MENU

async def show_top_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать топ трат по категориям"""
    conn = sqlite3.connect('finance_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses
        WHERE user_id = ? AND amount > 0
        GROUP BY category
        ORDER BY total DESC
        LIMIT 10
    ''', (update.effective_user.id,))
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        await update.message.reply_text("📊 У вас пока нет трат!")
        return MAIN_MENU
    
    response = "📊 *Топ трат:*\n\n"
    for idx, (category, total) in enumerate(results, 1):
        response += f"{idx}. {category} - {total:.2f} руб.\n"
    
    await update.message.reply_text(response, parse_mode="Markdown")
    return MAIN_MENU

async def show_average_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать средний расход за месяц и неделю"""
    conn = sqlite3.connect('finance_bot.db')
    cursor = conn.cursor()
    
    # Расход за весь период
    cursor.execute(
        'SELECT SUM(amount) FROM expenses WHERE user_id = ? AND amount > 0', 
        (update.effective_user.id,)
    )
    total_month = cursor.fetchone()[0] or 0
    
    # Расход за последние 7 дней
    week_ago = datetime.now() - timedelta(days=7)
    cursor.execute(
        'SELECT SUM(amount) FROM expenses WHERE user_id = ? AND amount > 0 AND date >= ?',
        (update.effective_user.id, week_ago)
    )
    total_week = cursor.fetchone()[0] or 0
    conn.close()
    
    response = "📈 *Статистика расходов:*\n\n"
    response += f"МЕСЯЦ - {total_month:.2f} рублей\n"
    response += f"НЕДЕЛЯ - {total_week:.2f} рублей"
    
    await update.message.reply_text(response, parse_mode="Markdown")
    return MAIN_MENU

async def calculate_money_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассчитать через сколько закончатся деньги"""
    conn = sqlite3.connect('finance_bot.db')
    cursor = conn.cursor()
    
    # Получаем зарплату
    cursor.execute('SELECT salary FROM users WHERE user_id = ?', (update.effective_user.id,))
    result = cursor.fetchone()
    
    if not result:
        await update.message.reply_text("⚠️ Сначала введите зарплату с помощью /start")
        conn.close()
        return MAIN_MENU
    
    salary = result[0]
    
    # Получаем общую сумму расходов
    cursor.execute('SELECT SUM(amount) FROM expenses WHERE user_id = ?', (update.effective_user.id,))
    total_expenses = cursor.fetchone()[0] or 0
    current_balance = salary - total_expenses
    
    # Средний расход в день
    cursor.execute('''
        SELECT AVG(daily_expense) FROM (
            SELECT DATE(date) as day, SUM(amount) as daily_expense
            FROM expenses
            WHERE user_id = ? AND amount > 0
            GROUP BY DATE(date)
        )
    ''', (update.effective_user.id,))
    avg_daily = cursor.fetchone()[0] or 0
    conn.close()
    
    if avg_daily == 0:
        await update.message.reply_text(
            f"⏰ *Расчет финансов:*\n\n"
            f"💰 Текущий баланс: {current_balance:.2f} руб.\n"
            f"📊 Недостаточно данных для расчета. Добавьте больше трат!",
            parse_mode="Markdown"
        )
        return MAIN_MENU
    
    if current_balance <= 0:
        await update.message.reply_text(
            f"⏰ *Расчет финансов:*\n\n"
            f"💰 Текущий баланс: {current_balance:.2f} руб.\n"
            f"⚠️ Деньги уже закончились!",
            parse_mode="Markdown"
        )
        return MAIN_MENU
    
    days_left = current_balance / avg_daily
    await update.message.reply_text(
        f"⏰ *Расчет финансов:*\n\n"
        f"💰 Текущий баланс: {current_balance:.2f} руб.\n"
        f"📊 Средний расход в день: {avg_daily:.2f} руб.\n"
        f"📅 Деньги закончатся примерно через: *{days_left:.1f} дней*",
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущей операции"""
    await update.message.reply_text("❌ Операция отменена.", reply_markup=get_main_menu())
    return MAIN_MENU

# ==================== WEBHOOK HANDLER (для деплоя) ====================

async def webhook_handler(event, context_lambda):
    """Handler для Yandex Cloud Functions (webhook)"""
    try:
        init_db()
        
        # Получаем токен из переменных окружения
        token = os.environ.get('BOT_TOKEN', BOT_TOKEN)
        application = Application.builder().token(token).build()
        
        # Настраиваем обработчики
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                WAITING_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_salary)],
                MAIN_MENU: [
                    MessageHandler(filters.Regex("^💸 Ввести трату/пополнение$"), add_expense),
                    MessageHandler(filters.Regex("^📊 Топ трат$"), show_top_expenses),
                    MessageHandler(filters.Regex("^📈 Средний расход$"), show_average_expense),
                    MessageHandler(filters.Regex("^⏰ Когда кончатся деньги$"), calculate_money_end)
                ],
                WAITING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_amount)],
                WAITING_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_category)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        application.add_handler(conv_handler)
        
        # Парсим запрос от Telegram
        body = json.loads(event['body'])
        update = Update.de_json(body, application.bot)
        
        # Обрабатываем обновление
        await application.process_update(update)
        
        return {'statusCode': 200, 'body': 'ok'}
    except Exception as e:
        logging.error(f"Error in webhook handler: {e}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

# Алиас для Yandex Cloud
handler = webhook_handler

# ==================== ЛОКАЛЬНЫЙ ЗАПУСК ====================

def main():
    """Локальный запуск бота через polling"""
    print("🔧 Инициализация базы данных...")
    init_db()
    
    print("🤖 Запуск бота...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Настраиваем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_salary)],
            MAIN_MENU: [
                MessageHandler(filters.Regex("^💸 Ввести трату/пополнение$"), add_expense),
                MessageHandler(filters.Regex("^📊 Топ трат$"), show_top_expenses),
                MessageHandler(filters.Regex("^📈 Средний расход$"), show_average_expense),
                MessageHandler(filters.Regex("^⏰ Когда кончатся деньги$"), calculate_money_end)
            ],
            WAITING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_amount)],
            WAITING_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_category)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(conv_handler)
    
    print("✅ Бот успешно запущен и работает!")
    print("💬 Напишите боту /start в Telegram")
    print("🛑 Для остановки нажмите Ctrl+C")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()