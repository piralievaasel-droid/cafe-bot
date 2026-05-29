# Cafe Inventory Telegram Bot

Telegram-бот для учёта товаров в кафе с интеграцией Google Sheets.

## Возможности
- Списание товаров сотрудниками
- Автоматическое создание заказов на пополнение при падении остатков ниже минимума
- Подтверждение поступления товаров администратором
- Логирование всех операций
- Ролевая модель (сотрудник / администратор)

## Технологии
- Python 3.11
- aiogram 3
- Google Sheets API
- FSM (конечные автоматы)

## Скриншоты работы

### Списание товара (Telegram)
![Списание](images/spisanie.jpeg)

### Создание заказа на пополнение (Telegram)
![Заказ в Telegram](images/zakaz_tb.jpeg)

### Приёмка товара админом (Telegram)
![Приёмка](images/priemka_tb.jpeg)

### Обновление остатков в Google Sheets
![Остатки](images/ostatki.jpeg)

### Лог пополнений в Google Sheets
![Лог пополнений](images/log_popolneniy.jpeg)

### История списаний сотрудника (Telegram)
![История списаний](images/istoriya_spisaniy.jpeg)

### Google Sheets — лист "Расход"
![Расход](images/расход%20г.т.jpeg)

### Заказ в Google Sheets (пример)
![Заказ GS](images/zakaz%20gs.jpeg)

### Дополнительно — лог пополнений (другой вид)
![Лог пополнений 2](images/log_popolneniy_gt.jpeg)

## Как запустить (для разработчика)
1. Клонируйте репозиторий
2. Создайте виртуальное окружение
3. Установите зависимости: `pip install -r requirements.txt`
4. Создайте `config.py` по образцу `config.example.py` и вставьте свои токены/ключи
5. Запустите бота: `python bot.py`

## Примечание
Файлы `config.py` и `service_account.json` не включены в репозиторий по соображениям безопасности. Они должны быть созданы локально.
