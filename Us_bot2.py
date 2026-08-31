import time
from datetime import datetime
import pytz
import requests
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from google import genai
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# === Render Health Check (ფონური ვებ-სერვერი Render-ისთვის) ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# გაეშვას ფონურ რეჟიმში
threading.Thread(target=run_health_check_server, daemon=True).start()

# === კონფიგურაცია ===
TELEGRAM_TOKEN = "8843403115:AAEzzflHHlPZn4yUGHIAlFdqWouZ9_3vE6A"
CHAT_ID = "-5259242498"
GEMINI_API_KEY = "AQ.Ab8RN6LN0-1b08y6tPfYtEfJoYTSDO2hDVv5WHe81khUJ66ejA"

FINNHUB_API_KEY = "d9b5341r01qmk4gk9hjgd9b5341r01qmk4gk9hk0"
ALPHA_VANTAGE_API_KEY = "NS35ORHRH8OLYEVB"

TICKERS = {
    "MNQ1! (Nasdaq 100 Micro Futures)": "MNQ=F",
    "ES1! (S&P 500 E-mini Futures)": "ES=F",
    "EUR/USD (Euro / US Dollar)": "EURUSD=X"
}

ai_client = genai.Client(api_key=GEMINI_API_KEY)

def log_message(text):
    georgia_tz = pytz.timezone('Asia/Tbilisi')
    now = datetime.now(georgia_tz).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {text}")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        elif response.status_code == 400 and "can't find end of" in response.text:
            log_message("⚠️ მონიშვნის (Markdown) შეცდომა. ვაგზავნით უბრალო ტექსტად...")
            payload.pop("parse_mode", None)
            fallback_res = requests.post(url, json=payload, timeout=10)
            return fallback_res.status_code == 200
        else:
            log_message(f"❌ ტელეგრამის API შეცდომა: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        log_message(f"❌ ტელეგრამთან კავშირის შეცდომა: {e}")
        return False

def get_forex_factory_news():
    news_summary = []
    url = "https://www.forexfactory.com/ff_calendar_thisweek.xml"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            today_str = datetime.now(pytz.timezone('America/New_York')).strftime('%m-%d-%Y')
            for event in root.findall('event'):
                event_date = event.find('date').text
                if event_date == today_str:
                    title = event.find('title').text
                    currency = event.find('currency').text
                    impact = event.find('impact').text
                    event_time = event.find('time').text
                    if impact in ['High', 'Medium'] and currency in ['USD', 'EUR']:
                        news_summary.append(f"• [{event_time}] {currency} - {title} (გავლენა: {impact})")
        return "\n".join(news_summary) if news_summary else "მნიშვნელოვანი ეკონომიკური სიახლეები დღეს არ არის დაგეგმილი."
    except Exception as e:
        log_message(f"Forex Factory შეცდომა: {e}")
        return "Forex Factory-ს მონაცემების მიღება ვერ მოხერხდა."

def get_finnhub_news():
    if not FINNHUB_API_KEY or FINNHUB_API_KEY == "აქ_ჩასვი_FINNHUB_API_KEY":
        return "Finnhub API გასაღები არ არის კონფიგურირებული."
    url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            news_data = response.json()
            summary = [f"• {item.get('headline', '')}" for item in news_data[:3]]
            return "\n".join(summary) if summary else "Finnhub-ზე სიახლეები არ მოიძებნა."
        return "Finnhub-იდან მონაცემების მიღება ჩაიშალა."
    except Exception as e:
        log_message(f"Finnhub შეცდომა: {e}")
        return f"Finnhub შეცდომა: {e}"

def get_alpha_vantage_news():
    if not ALPHA_VANTAGE_API_KEY or ALPHA_VANTAGE_API_KEY == "აქ_ჩასვი_ALPHA_VANTAGE_API_KEY":
        return "Alpha Vantage API გასაღები არ არის კონფიგურირებული."
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            feed = response.json().get('feed', [])
            summary = [f"• {item.get('title', '')} (სენტიმენტი: {item.get('overall_sentiment_label', 'Neutral')})" for item in feed[:3]]
            return "\n".join(summary) if summary else "Alpha Vantage-ზე სიახლეები არ მოიძებნა."
        return "Alpha Vantage-იდან მონაცემების მიღება ჩაიშალა."
    except Exception as e:
        log_message(f"Alpha Vantage შეცდომა: {e}")
        return f"Alpha Vantage შეცდომა: {e}"

def get_market_data():
    market_report = []
    for display_name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            fast_info = ticker.fast_info
            current_price = fast_info.last_price if hasattr(fast_info, 'last_price') else None
            day_change = fast_info.day_change_percent if hasattr(fast_info, 'day_change_percent') else 0
            if not current_price:
                history = ticker.history(period="1d", interval="1m")
                if not history.empty:
                    current_price = history['Close'].iloc[-1]
            market_report.append(f"- {display_name}: ფასი = {current_price:.5f}, დღიური ცვლილება = {day_change:.2f}%")
        except Exception as e:
            log_message(f"ფასის წაკითხვის შეცდომა {ticker_symbol}-ზე: {e}")
            market_report.append(f"- {display_name}: მონაცემები დროებით მიუწვდომელია")
    return "\n".join(market_report)

def get_candlesticks_data():
    full_candles_report = []
    for display_name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            ticker_report = [f"📈 **{display_name} (Multi-Timeframe Analysis):**"]
            
            # 1. 4h (10 სანთელი)
            df_1h = ticker.history(period="7d", interval="1h")
            if not df_1h.empty:
                ohlc_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
                df_4h = df_1h.resample('4h').apply(ohlc_dict).dropna().tail(10)
                ticker_report.append("  🕒 **4-საათიანი (4h) - ბოლო 10 სანთელი:**")
                for timestamp, row in df_4h.iterrows():
                    t_str = timestamp.strftime('%m-%d %H:%M')
                    o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
                    c_type = "🟢" if c >= o else "🔴"
                    ticker_report.append(f"    • [{t_str}] {c_type} O: {o:.5f} | H: {h:.5f} | L: {l:.5f} | C: {c:.5f}")

            # 2. 1h (5 სანთელი)
            if not df_1h.empty:
                df_1h_tail = df_1h.tail(5)
                ticker_report.append("  🕐 **1-საათიანი (1h) - ბოლო 5 სანთელი:**")
                for timestamp, row in df_1h_tail.iterrows():
                    t_str = timestamp.strftime('%m-%d %H:%M')
                    o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
                    c_type = "🟢" if c >= o else "🔴"
                    ticker_report.append(f"    • [{t_str}] {c_type} O: {o:.5f} | H: {h:.5f} | L: {l:.5f} | C: {c:.5f}")

            # 3. 5m (30 სანთელი)
            df_5m = ticker.history(period="5d", interval="5m")
            if not df_5m.empty:
                df_5m_tail = df_5m.tail(30)
                ticker_report.append("  ⏱️ **5-წუთიანი (5m) - ბოლო 30 სანთელი:**")
                for timestamp, row in df_5m_tail.iterrows():
                    t_str = timestamp.strftime('%H:%M')
                    o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
                    c_type = "🟢" if c >= o else "🔴"
                    ticker_report.append(f"    • [{t_str}] {c_type} O: {o:.5f} | H: {h:.5f} | L: {l:.5f} | C: {c:.5f}")

            # 4. 1m (30 სანთელი)
            df_1m = ticker.history(period="2d", interval="1m")
            if not df_1m.empty:
                df_1m_tail = df_1m.tail(30)
                ticker_report.append("  ⚡ **1-წუთიანი (1m) - ბოლო 30 სანთელი:**")
                for timestamp, row in df_1m_tail.iterrows():
                    t_str = timestamp.strftime('%H:%M')
                    o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
                    c_type = "🟢" if c >= o else "🔴"
                    ticker_report.append(f"    • [{t_str}] {c_type} O: {o:.5f} | H: {h:.5f} | L: {l:.5f} | C: {c:.5f}")

            if "EUR/USD" in display_name and not df_1m.empty:
                unique_prices = df_1m['Close'].tail(30).nunique()
                if unique_prices == 1:
                    log_message(f"⚠️ გაფრთხილება: {display_name}-ის ბოლო 30 წუთში ფასის ცვლილება არ ფიქსირდება (Close = {df_1m['Close'].iloc[-1]:.5f}).")

            full_candles_report.append("\n".join(ticker_report))

        except Exception as e:
            log_message(f"სანთლების დამუშავების შეცდომა {ticker_symbol}-ზე: {e}")
            full_candles_report.append(f"📌 {display_name}: სანთლების დამუშავება ჩაიშალა.")

    return "\n\n".join(full_candles_report)

def generate_premarket_report():
    log_message("⏳ იწყება წინასაბაზრო რეპორტის მომზადება (ფასები + Multi-TF სანთლები + ნიუსები)...")
    market_data = get_market_data()
    candlesticks_data = get_candlesticks_data()
    ff_news = get_forex_factory_news()
    finnhub_news = get_finnhub_news()
    alpha_news = get_alpha_vantage_news()
    
    prompt = f"""
    შენ ხარ წამყვანი Wall Street-ის ანალიტიკოსი და მაკრო ტრეიდერი.
    ნიუ-იორკის საფონდო ბირჟის (NYSE) გახსნამდე დარჩა ზუსტად 10 წუთი.
    
    მიმდინარე წინასაბაზრო (Pre-market) ფასები და ტრენდები:
    {market_data}
    
    📊 მულტი-თაიმფრეიმული ტექნიკური ანალიზი (4h: 10 სანთელი, 1h: 5 სანთელი, 5m: 30 სანთელი, 1m: 30 სანთელი):
    {candlesticks_data}
    
    დღევანდელი მნიშვნელოვანი Forex Factory ეკონომიკური კალენდარი:
    {ff_news}
    
    Finnhub-ის უახლესი გლობალური საფონდო სიახლეები:
    {finnhub_news}
    
    Alpha Vantage-ის უახლესი სიახლეები და სენტიმენტები:
    {alpha_news}
    
    ამ მონაცემებზე (განსაკუთრებით Multi-TF სანთლების ტექნიკურ სტრუქტურაზე) დაყრდნობით, გააკეთე დღის მოკლევადიანი პროგნოზი მომდევნო 10-15 წუთიდან რამდენიმე საათის პერსპექტივით.
    ჩამოაყალიბე ზუსტად 3 ყველაზე მომგებიანი და ლოგიკური ტრეიდის ვარიანტი ამ სამი აქტივიდან გამომდინარე.
    
    პასუხი დააფორმატე Markdown სტილში ქართულ ენაზე ზუსტად ასე:
    🔔 **ნიუ-იორკის ბირჟის გახსნის რეპორტი (Pre-Market)**
    
    *ბაზრის საერთო განწყობა (Sentiment):* (აქ დაწერე მოკლე მაკროეკონომიკური და ტექნიკური ანალიზი, თუ როგორ იმოქმედებს ნიუსები და Multi-TF სანთლები წინასაბაზრო ფასებთან კომბინაციაში)
    
    📊 **დღევანდელი Forex Factory კალენდარი:**
    (აქ ჩამოწერე ზემოთ მოყვანილი Forex Factory-ს დღევანდელი ეკონომიკური კალენდარი/სიახლეები)
    
    📰 **Finnhub და Alpha Vantage სიახლეები:**
    {finnhub_news}
    {alpha_news}
    
    **💡 ტრეიდი #1: [აქტივის სახელი - LONG ან SHORT]**
    - შესვლის წერტილი (Entry):
    - თეიქ პროფიტი (Take Profit):
    - სტოპ ლოსი (Stop Loss):
    - წარმატების ალბათობა: [მაგ. 85%]
    
    **💡 ტრეიდი #2:** ...
    **💡 ტრეიდი #3:** ...
    """
    
    max_retries = 5
    retry_delay = 15
    
    for attempt in range(max_retries):
        try:
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            if send_telegram_message(response.text):
                log_message("✅ რეპორტი წარმატებით გაიგზავნა ტელეგრამში.")
                return True
        except Exception as e:
            log_message(f"⚠️ Gemini შეცდომა (მცდელობა {attempt + 1}/{max_retries}): {e}")
        
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
            
    log_message("❌ ყველა მცდელობა ჩაიშალა. რეპორტი ვერ გაიგზავნა.")
    return False

def main_loop():
    log_message("🚀 ბოტი გადავიდა ყოველდღიური რეპორტის რეჟიმში (09:20 AM EST)...")
    last_run_date = None
    
    while True:
        ny_timezone = pytz.timezone('America/New_York')
        current_time_ny = datetime.now(ny_timezone)
        
        current_date = current_time_ny.date()
        current_hour = current_time_ny.hour
        current_minute = current_time_ny.minute
        current_weekday = current_time_ny.weekday()

        if current_weekday < 5:
            if current_hour == 9 and current_minute == 20 and current_date != last_run_date:
                report_success = generate_premarket_report()
                if report_success:
                    last_run_date = current_date
                
        time.sleep(30)

if __name__ == "__main__":
    main_loop()
