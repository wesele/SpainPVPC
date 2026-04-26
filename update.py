import json
import requests
import urllib3
from datetime import datetime, timedelta, timezone
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SPAIN_OFFSET = timedelta(hours=2)

def spain_now():
    return (datetime.now(timezone.utc) + SPAIN_OFFSET).replace(tzinfo=None)

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*'
})

def load_pvpc_data():
    try:
        with open('pvpc.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_pvpc_data(data):
    with open('pvpc.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def format_date(date):
    return date.strftime('%Y-%m-%d')

def is_data_complete(data):
    today = spain_now()
    now_hour = today.hour
    for day_offset in range(10):
        date = today - timedelta(days=9 - day_offset)
        date_str = format_date(date)
        
        if date_str not in data:
            return False
        
        expected = 24 if date_str < format_date(today) else min(now_hour + 1, 24)
        if len(data[date_str]) < expected:
            return False
        
        prices = data[date_str]
        if all(p == 0 for p in prices):
            return False
        
        for other_date_str in data:
            if other_date_str != date_str and data[other_date_str] == prices:
                return False
    return True

def fetch_from_ree_api(date, date_str=None):
    try:
        if date_str is None:
            date_str = format_date(date)
        start_date = f"{date_str}T00:00:00"
        end_date = f"{date_str}T23:59:59"
        
        url = f'https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real?start_date={start_date}&end_date={end_date}&time_trunc=hour'
        
        response = SESSION.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'included' in data and len(data['included']) > 0:
                values = data['included'][0]['attributes']['values']
                prices = [round(v['value'], 4) for v in values]
                
                if len(prices) > 0:
                    if len(prices) < 24:
                        print(f"  从REE API获取到 {len(prices)} 小时数据（不完整）")
                    return prices
                else:
                    print(f"  从REE API获取到0小时数据")
                    
    except Exception as e:
        print(f"  从REE API获取数据失败: {e}")
    return None

def should_update_date(date_str, data):
    if date_str not in data:
        return True
    prices = data[date_str]
    if len(prices) == 0:
        return True
    if all(p == 0 for p in prices):
        return True
    for other_date_str in data:
        if other_date_str != date_str and data[other_date_str] == prices:
            return True
    today_str = format_date(spain_now())
    now_hour = spain_now().hour
    if date_str == today_str and len(prices) <= now_hour:
        return True
    return False

def update_pvpc_data():
    print("检查pvpc.json数据...")
    
    data = load_pvpc_data()
    
    if is_data_complete(data):
        print("\u2713 数据已完整（过去10天）")
        return data
    
    print("数据不完整，开始更新...")
    
    today = spain_now()
    updated = False
    
    for day_offset in range(10):
        date = today - timedelta(days=9 - day_offset)
        date_str = format_date(date)
        
        if should_update_date(date_str, data):
            print(f"获取 {date_str} 的数据...")
            
            prices = fetch_from_ree_api(date, date_str)
            
            if prices:
                data[date_str] = prices
                updated = True
                print(f"\u2713 {date_str} 数据获取成功")
            else:
                print(f"\u2717 {date_str} 数据获取失败")
    
    if updated:
        cutoff_date = today - timedelta(days=9)
        cutoff_str = format_date(cutoff_date)
        data = {k: v for k, v in data.items() if k >= cutoff_str}
        
        save_pvpc_data(data)
        print("\u2713 数据已保存到 pvpc.json")
    else:
        print("\u2717 没有获取到新数据")
    
    return data

if __name__ == '__main__':
    update_pvpc_data()
