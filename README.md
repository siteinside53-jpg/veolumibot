# veolumibot
## AI Marketplace Telegram Bot (Greek)

### Env vars (Railway Variables)
- BOT_TOKEN=xxxxxxxx
- DATABASE_URL=postgresql://...
- (optional) WEBHOOK_BASE_URL=https://your-app.up.railway.app
- PORT=8080 (Railway το δίνει αυτόματα)

### Run locally
pip install -r requirements.txt
export BOT_TOKEN=...
export DATABASE_URL=...
python main.py

### curl https://api.telegram.org/bot<TOKEN>/deleteWebhook?drop_pending_updates=true
