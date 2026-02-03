# ... المحتوى الأصلي السابق كما هو ...

# ===== Telegram Bot =====
class TelegramBot:
    def __init__(self):
        self.updater = Updater(TELEGRAM_TOKEN, use_context=True)
        self.dp = self.updater.dispatcher
        self.data_engine = DataEngine()
        self.predictor = AIPredictor()

        # Handlers
        self.dp.add_handler(CommandHandler("start", self.start_cmd))

    def start_cmd(self, update: Update, context: CallbackContext):
        update.message.reply_text("✅ Predictor Bot Active")

    def find_and_alert(self, job):
        try:
            live_data = self.data_engine.get_live_data()
            value_bets = self.predictor.find_value_bets(live_data)

            if not value_bets.empty:
                for _, bet in value_bets.iterrows():
                    message = (
                        f"⚡ Value Bet Detected!\n"
                        f"🏆 {bet['match']}\n"
                        f"💰 Odd: {bet['odds']}\n"
                        f"📊 Edge: +{bet['edge']}%\n"
                    )
                    self.updater.bot.send_message(
                        chat_id=CHAT_ID,
                        text=message
                    )
        except Exception as e:
            logging.error(f"Alert error: {e}")

    def run(self):
        job_queue = self.updater.job_queue
        job_queue.run_repeating(self.find_and_alert, interval=SCRAPE_INTERVAL, first=10)
        self.updater.start_polling()
        self.updater.idle()

# === Flask Server for Render ===
import os
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def health_check():
    return "⚡ Bot Active | Use Telegram to interact"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# === Main Execution ===
if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Start Flask server in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram bot
    bot = TelegramBot()
    bot.run()
