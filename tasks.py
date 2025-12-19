
import time, os, joblib
from datetime import datetime, timedelta
import yfinance as yf, feedparser
from textblob import TextBlob
from collections import deque

STOCKS_FILE = os.path.join('data','stocks.csv')
ALERTS = deque(maxlen=500)
LAST_ALERT = {}
MODEL_PATH = 'trend_model.joblib'

def load_stock_list():
    if os.path.exists(STOCKS_FILE):
        with open(STOCKS_FILE) as f:
            return [line.strip() for line in f if line.strip()]
    return ['RELIANCE.NS','TCS.NS','INFY.NS','HDFCBANK.NS','ICICIBANK.NS','SBIN.NS']

STOCKS = load_stock_list()

def search_stocks(query):
    if not query: return []
    q = query.lower()
    out = [s for s in STOCKS if q in s.lower() or q in s.lower().replace('.ns','')]
    return [{'symbol':s,'name':s} for s in out[:50]]

def get_today_change(sym):
    try:
        data = yf.Ticker(sym).history(period='1d')
        if data.empty: return 0.0
        o = data['Open'].iloc[0]; c = data['Close'].iloc[-1]
        return round(((c-o)/o)*100,2)
    except Exception as e:
        return 0.0

def get_intraday(sym):
    try:
        data = yf.Ticker(sym).history(period='1d', interval='30m')
        return [round(x,2) for x in data['Close'].tail(20).tolist()]
    except Exception as e:
        return []

def check_news(company):
    feed = feedparser.parse(f'https://news.google.com/rss/search?q={company}+stock')
    sentiments=[]; headlines=[]
    for e in feed.entries[:5]:
        try:
            sentiments.append(TextBlob(e.title).sentiment.polarity)
            headlines.append(e.title)
        except:
            pass
    if not sentiments: return None,0
    return headlines[0], sum(sentiments)/len(sentiments)

def start_background_tasks():
    batch_size = 20
    idx = 0
    while True:
        batch = STOCKS[idx:idx+batch_size]
        if not batch:
            idx = 0; time.sleep(10); continue
        for sym in batch:
            try:
                change = get_today_change(sym)
                if abs(change) >= 1.5:
                    headline, sentiment = check_news(sym.replace('.NS',''))
                    ALERTS.appendleft({'symbol':sym,'change':change,'headline':headline or '', 'sentiment': sentiment, 'time':datetime.now().strftime('%H:%M')})
                    LAST_ALERT[sym]=datetime.now()
            except Exception:
                pass
            time.sleep(1)
        idx += batch_size
        time.sleep(15)

def get_latest_alerts():
    return list(ALERTS)[:50]

def get_trending_rows():
    rows=[]
    for s in STOCKS:
        rows.append({'symbol':s, 'name':s, 'change': get_today_change(s), 'spark': get_intraday(s)})
    gainers=sorted(rows, key=lambda x: x['change'], reverse=True)[:10]
    losers=sorted(rows, key=lambda x: x['change'])[:10]
    return gainers, losers, rows

def get_watchlist_rows(user_id):
    rows=[]
    for s in STOCKS[:5]:
        rows.append({'symbol':s,'name':s,'change':get_today_change(s)})
    return rows

def get_stock_history_for_chart(symbol):
    return get_intraday(symbol)

def train_model_if_needed():
    while True:
        try:
            import numpy as np
            from sklearn.ensemble import RandomForestClassifier
            X=[]; y=[]
            for s in STOCKS[:100]:
                hist = yf.Ticker(s).history(period='60d')
                if len(hist)<10: continue
                closes = hist['Close'].tolist()
                for i in range(5,len(closes)-1):
                    feat = [(closes[i-j]-closes[i-j-1])/closes[i-j-1] for j in range(1,6)]
                    X.append(feat); y.append(1 if closes[i+1]>closes[i] else 0)
            if X:
                clf = RandomForestClassifier(n_estimators=30, random_state=42)
                clf.fit(X,y)
                joblib.dump(clf, MODEL_PATH)
        except Exception:
            pass
        time.sleep(24*3600)
