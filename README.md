# Scooter Promo Bot

Telegram bot for scooter promo code sales with:
- menu (`Аккаунт`, `Тарифы`, `Подписки`, `Помощь`)
- YooMoney payment links
- payment status check via YooMoney API
- promo code issuance after successful payment

## Products in bot

Tariffs:
- 60 minutes - 150 RUB
- 60 minutes (for you and friend) - 250 RUB
- 120 minutes - 300 RUB
- 180 minutes - 450 RUB
- 300 minutes - 600 RUB

Subscriptions:
- 1 day for 1 RUB offer - 500 RUB
- 5 days for 1 RUB offer - 1250 RUB
- Worker account (free rides) - 3000 RUB

## Setup

1. Install Python 3.11+
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from template:

```bash
copy .env.example .env
```

4. Fill `.env` values:
- `BOT_TOKEN`
- `ADMIN_ID`
- `YOOMONEY_ACCESS_TOKEN`
- `YOOMONEY_WALLET`

5. Run bot:

```bash
python bot.py
```

## Security note

Do not commit `.env` into git.  
If tokens were shared publicly, rotate them immediately in BotFather and YooMoney.
