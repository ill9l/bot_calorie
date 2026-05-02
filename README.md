# 🥗 Calorie Tracker Bot

Telegram-бот для відстеження калорій з аналізом їжі через ШІ.

## Що вміє

- 📸 Розпізнає їжу на фото та рахує калорії (через Claude AI)
- 📎 Обробляє кілька фото одночасно як один прийом їжі
- ⚖️ Враховує вагу тарілки (тара) при зважуванні на терезах
- 📊 Показує денний підсумок: калорії, білки, вуглеводи, жири
- 📅 Зберігає історію харчування (календар за 14 днів)
- ✏️ Дозволяє редагувати та видаляти записи
- 🎯 Персональна ціль калорій для кожного користувача

## Технології

- **Python** — основна мова
- **python-telegram-bot** — Telegram Bot API
- **Anthropic Claude API** — аналіз фото їжі та розпізнавання тексту
- **MongoDB** — зберігання даних користувачів
- **python-dotenv** — керування змінними середовища

## Команди

| Команда | Опис |
|---|---|
| `/start` | Запустити бота |
| `/day` | Підсумок за сьогодні |
| `/goal 2000` | Встановити ціль калорій |
| `/tara 417` | Вага тарілки в грамах |
| `/calendar` | Історія за 14 днів |
| `/reset` | Скинути записи за день |


🥗 CalorieBot — AI-Powered Nutrition Tracker for Telegram
A personal Telegram bot that uses Claude AI (Anthropic) to recognize food from photos and text descriptions, estimate calories, and track daily nutrition goals.

Built as a personal project to support my own weight loss journey — and to explore practical AI integration.


✨ Features
📸 Photo recognition — send a food photo, get an instant calorie estimate powered by Claude Vision API
📝 Text logging — describe what you ate in free text, the bot parses and estimates calories
📊 Daily progress bar — visual progress toward your daily calorie goal
🗓 Calendar view — browse your nutrition history by date
➕ Full CRUD — add, view, and delete individual food entries via inline keyboard
👥 Multi-user support — each user has their own isolated data
⚙️ Custom commands — set your daily calorie goal and tare weight


🛠 Tech Stack
Component
Technology
Language
Python 3
Telegram framework
python-telegram-bot
AI / Vision
Claude API (Anthropic)
Data storage
JSON



🚀 How to Run
Clone the repo

git clone https://github.com/ill9l/bot_calorie.git

cd bot_calorie

Install dependencies

pip install -r requirements.txt

Set up environment variables

Create a .env file in the root:

TELEGRAM_BOT_TOKEN=your_telegram_bot_token

ANTHROPIC_API_KEY=your_anthropic_api_key

Run the bot

python bot.py


💡 Why I Built This
I wanted a simple way to track my calories without manual lookup — just take a photo or describe what I ate and get an instant estimate.

It also became my hands-on introduction to AI API integration: structuring prompts, parsing LLM responses as JSON, and building a real product around it end-to-end.


📌 Status
Active — used daily for personal nutrition tracking.

## Запуск локально

1. Клонуй репозиторій
```bash
git clone https://github.com/ill9l/bot_calorie.git
cd bot_calorie
```

2. Встанови залежності
```bash
pip install -r requirements.txt
```

3. Створи `.env` файл
```
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
MONGO_URI=your_mongodb_connection_string
```

4. Запусти бота
```bash
python bot.py
```

> ⚠️ Бот працює поки запущений локально. Для роботи 24/7 можна задеплоїти на Railway або Render.
