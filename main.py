import cloudscraper
import pandas as pd
import numpy as np
import xgboost as xgb
import random
import time
import logging
import hashlib
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

# ===== Configuration =====
TELEGRAM_TOKEN = "8434452399:AAEbC0i6-8gC4EsjKH7j0qeWy8WtBGkZYVs"
CHAT_ID = "8323244727"
SCRAPE_INTERVAL = 300  # 5 minutes
VALUE_THRESHOLD = 0.15  # 15% edge

# ===== Data Engine =====
class DataEngine:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5)'
        ]

    def _get_headers(self):
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://google.com/'
        }

    def scrape_linebet(self):
        try:
            response = self.scraper.get(
                'https://linebet.com/en/live/football',
                headers=self._get_headers(),
                timeout=20
            )
            
            soup = BeautifulSoup(response.text, 'html.parser')
            matches = []
            
            for match in soup.select('div.event__match'):
                try:
                    home = match.select_one('div.event__participant--home').text.strip()
                    away = match.select_one('div.event__participant--away').text.strip()
                    odds = [
                        float(odd.text.strip()) 
                        for odd in match.select('div.odds__price')[:3]
                    ]
                    
                    matches.append({
                        'home': home,
                        'away': away,
                        '1': odds[0],
                        'X': odds[1],
                        '2': odds[2]
                    })
                except Exception as e:
                    logging.error(f"Linebet match parse error: {e}")
                    continue
            
            return pd.DataFrame(matches)
        
        except Exception as e:
            logging.error(f"Linebet scrape failed: {e}")
            return pd.DataFrame()

    def scrape_flashscore(self):
        try:
            response = self.scraper.get(
                'https://www.flashscore.com/football/',
                headers=self._get_headers(),
                timeout=20
            )
            
            soup = BeautifulSoup(response.text, 'html.parser')
            stats = []
            
            for match in soup.select('div.event__match'):
                try:
                    teams = match.select('div.event__participant')
                    stat_row = match.select_one('div.event__stats')
                    
                    if stat_row:
                        shots = stat_row.text.split()
                        home_shots = int(shots[0])
                        away_shots = int(shots[2])
                        
                        stats.append({
                            'home': teams[0].text.strip(),
                            'away': teams[1].text.strip(),
                            'home_shots': home_shots,
                            'away_shots': away_shots,
                        })
                except Exception as e:
                    logging.error(f"Flashscore match parse error: {e}")
                    continue
            
            return pd.DataFrame(stats)
        
        except Exception as e:
            logging.error(f"Flashscore scrape failed: {e}")
            return pd.DataFrame()

    def get_live_data(self):
        linebet_df = self.scrape_linebet()
        flashscore_df = self.scrape_flashscore()
        
        if not linebet_df.empty and not flashscore_df.empty:
            merged = pd.merge(
                linebet_df, 
                flashscore_df,
                on=['home', 'away'],
                how='inner'
            )
            merged['match_id'] = merged['home'] + '_' + merged['away']
            return merged
        return pd.DataFrame()

# ===== AI Predictor =====
class AIPredictor:
    def __init__(self):
        self.model = xgb.XGBClassifier(
            n_estimators=400,
            max_depth=8,
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric='logloss'
        )
        self._initialize_model()

    def _initialize_model(self):
        # Synthetic data generation
        np.random.seed(42)
        n_samples = 4000
        
        synthetic = pd.DataFrame({
            '1': np.random.uniform(1.5, 6.5, n_samples),
            'X': np.random.uniform(3.0, 5.0, n_samples),
            '2': np.random.uniform(1.5, 7.0, n_samples),
            'home_shots': np.random.randint(2, 20, n_samples),
            'away_shots': np.random.randint(1, 18, n_samples)
        })
        
        synthetic['output'] = np.where(
            synthetic['home_shots'] > synthetic['away_shots'], 
            (synthetic['1'] < 2.0).astype(int),
            (synthetic['2'] < 2.2).astype(int)
        )
        
        self.model.fit(self._create_features(synthetic), synthetic['output'])

    def _create_features(self, df):
        df = df.copy()
        df['probability_home'] = 1 / df['1']
        df['probability_draw'] = 1 / df['X']
        df['probability_away'] = 1 / df['2']
        df['shot_difference'] = df['home_shots'] - df['away_shots']
        return df[['probability_home', 'probability_draw', 'probability_away', 'shot_difference']]

    def find_value_bets(self, df):
        if df.empty:
            return pd.DataFrame()
        
        features = self._create_features(df)
        predictions = self.model.predict_proba(features)
        df['model_prob'] = predictions[:, 1]
        
        value_bets = []
        for _, row in df.iterrows():
            best_prob = np.max([1/row['1'], 1/row['X'], 1/row['2']])
            if (row['model_prob'] - best_prob) > VALUE_THRESHOLD:
                value_bets.append({
                    'match': f"{row['home']} vs {row['away']}",
                    'market': '1X2',
                    'odds': round(row[['1','X','2']].max(), 2),
                    'edge': round((row['model_prob'] - best_prob)*100, 1),
                })
        
        return pd.DataFrame(value_bets)

# ===== Telegram Bot =====
class BettingBot:
    def __init__(self):
        self.updater = Updater(TELEGRAM_TOKEN, use_context=True)
        self.data_engine = DataEngine()
        self.predictor = AIPredictor()
        self.active_alerts = set()
        
        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler("start", self._start))
        dp.add_handler(CommandHandler("value", self._get_value_bets))
    
    def _start(self, update: Update, context: CallbackContext):
        context.bot.send_message(
            chat_id=CHAT_ID,
            text="🔥 Betting Bot Online\n\nCommands:\n/value - Get
