# AI Marketplace Telegram (Template)

## Railway Setup
1) Push repo to GitHub
2) Railway -> New Project -> Deploy from GitHub
3) Add PostgreSQL plugin

## Create 2 services
### Service A: web
Start Command:
uvicorn app.web:api --host 0.0.0.0 --port $PORT

### Service B: bot
Start Command:
python -m app.bot

## ENV vars (και στα 2 services)
BOT_TOKEN=...
DATABASE_URL=... (από PostgreSQL plugin)
WEBAPP_URL=https://YOUR-WEB-SERVICE-URL

## Payments
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...

CRYPTOCLOUD_API_KEY=...
CRYPTOCLOUD_SHOP_ID=...
CRYPTOCLOUD_WEBHOOK_SECRET=...

## Stripe webhooks
Set webhook endpoint to:
https://YOUR-WEB-SERVICE-URL/api/stripe/webhook
Event: checkout.session.completed

## CryptoCloud webhooks
Set webhook endpoint to:
https://YOUR-WEB-SERVICE-URL/api/cryptocloud/webhook
