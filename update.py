import json
import requests
import urllib3
import statistics
from datetime import datetime, timedelta
import os
import sys
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 设置Windows控制台编码为UTF-8
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
    """加载pvpc.json数据"""
    try:
        with open('pvpc.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_pvpc_data(data):
    """保存数据到pvpc.json"""
    with open('pvpc.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def format_date(date):
    """格式化日期为 YYYY-MM-DD"""
    return date.strftime('%Y-%m-%d')

def is_data_complete(data):
    """检查是否有足够的完整数据（过去10天）"""
    today = datetime.now()
    for day_offset in range(10):
        date = today - timedelta(days=9 - day_offset)
        date_str = format_date(date)
        
        if date_str not in data or len(data[date_str]) < 24:
            return False
        
        # 检查数据是否有效（不能全为0）
        prices = data[date_str]
        if all(p == 0 for p in prices):
            return False
        
        # 检查是否与任何其他日期的数据完全相同（可能是复制错误）
        for other_date_str in data:
            if other_date_str != date_str and data[other_date_str] == prices:
                return False
    return True

def get_spain_offset_utc(date):
    """返回西班牙时区相对于UTC的偏移小时数（考虑夏令时）"""
    import calendar
    year = date.year
    march_last = max(week[-1] for week in calendar.monthcalendar(year, 3))
    october_last = max(week[-1] for week in calendar.monthcalendar(year, 10))
    dst_start = datetime(year, 3, march_last, 2, 0, 0)
    dst_end = datetime(year, 10, october_last, 3, 0, 0)
    naive_date = datetime(date.year, date.month, date.day)
    if dst_start <= naive_date < dst_end:
        return 2
    return 1

def fetch_from_ree_api(date):
    """从REE API获取指定日期的电价数据"""
    try:
        date_str = format_date(date)
        offset = get_spain_offset_utc(date)
        prev_date = date - timedelta(days=1)
        prev_date_str = format_date(prev_date)
        start_date = f"{prev_date_str}T{22-offset:02d}:00:00Z"
        end_date = f"{date_str}T{21-offset:02d}:59:59Z"
        
        url = f'https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real?start_date={start_date}&end_date={end_date}&time_trunc=hour'
        
        response = SESSION.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # 解析数据
            if 'included' in data and len(data['included']) > 0:
                values = data['included'][0]['attributes']['values']
                prices = [round(v['value'], 4) for v in values]
                
                if len(prices) == 24:
                    return prices
                else:
                    print(f"  从REE API获取到 {len(prices)} 小时数据，需要24小时")
                    
    except Exception as e:
        print(f"  从REE API获取数据失败: {e}")
    return None

def fetch_from_html(date):
    """从HTML页面获取指定日期的电价数据（备用方案）"""
    try:
        date_str = format_date(date)
        today = format_date(datetime.now())
        
        # 只能从主页获取当前日期的数据
        if date_str != today:
            print(f"  {date_str} 不是当前日期，无法从HTML获取历史数据")
            return None
            
        url = 'https://tarifaluzhora.es'
        
        response = SESSION.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找所有包含电价信息的元素
            prices = []
            price_elements = soup.find_all('span', itemprop='price')
            
            for element in price_elements:
                price_text = element.get_text()
                # 格式: "0,1325 €/kWh" -> 转换为数字
                try:
                    # 移除 €/kWh 并替换逗号为点
                    price_str = price_text.replace('€/kWh', '').replace(',', '.').strip()
                    price = float(price_str)
                    prices.append(round(price * 1000, 4))  # 转换为 €/MWh
                except ValueError:
                    continue
            
            if len(prices) == 24:
                return prices
            else:
                print(f"  从HTML获取到 {len(prices)} 小时数据，需要24小时")
                
    except Exception as e:
        print(f"  从HTML获取 {date_str} 数据失败: {e}")
    return None

def fetch_from_api(date):
    """从API获取指定日期的电价数据"""
    try:
        date_str = format_date(date)
        
        url = f'https://tarifaluzhora.es/api/prices/{date_str}'
        
        try:
            response = SESSION.get(url, timeout=10)
            if response.status_code == 200:
                prices = response.json()
                return [round(item['price'] * 1000, 4) for item in prices]
        except Exception as e:
            print(f"  尝试 {url} 失败: {e}")
                
    except Exception as e:
        print(f"获取 {date_str} 数据失败: {e}")
    return None

def should_update_date(date_str, data):
    """检查某天的数据是否需要更新"""
    if date_str not in data or len(data[date_str]) < 24:
        return True
    
    prices = data[date_str]
    
    # 检查数据是否有效（不能全为0）
    if all(p == 0 for p in prices):
        return True
    
    # 检查是否与任何其他日期的数据完全相同（可能是复制错误）
    for other_date_str in data:
        if other_date_str != date_str and data[other_date_str] == prices:
            return True
    
    # 检查是否与任何其他日期的数据的统计特征非常相似（可能是复制错误）
    mean = statistics.mean(prices)
    stdev = statistics.stdev(prices) if len(prices) > 1 else 0
    
    for other_date_str in data:
        if other_date_str != date_str and len(data[other_date_str]) == 24:
            other_mean = statistics.mean(data[other_date_str])
            other_stdev = statistics.stdev(data[other_date_str]) if len(data[other_date_str]) > 1 else 0
            
            # 如果均值和标准差都非常接近，认为数据可疑
            if abs(mean - other_mean) < 0.5 and abs(stdev - other_stdev) < 0.5:
                return True
    
    return False

def update_pvpc_data():
    """更新pvpc.json数据"""
    print("检查pvpc.json数据...")
    
    # 加载现有数据
    data = load_pvpc_data()
    
    # 检查数据是否完整
    if is_data_complete(data):
        print("✓ 数据已完整（过去10天）")
        return data
    
    print("数据不完整，开始更新...")
    
    # 获取过去10天的数据
    today = datetime.now()
    updated = False
    
    for day_offset in range(10):
        date = today - timedelta(days=9 - day_offset)
        date_str = format_date(date)
        
        if should_update_date(date_str, data):
            print(f"获取 {date_str} 的数据...")
            
            # 优先尝试REE API
            prices = fetch_from_ree_api(date)
            
            # 如果REE API失败，尝试其他API
            if not prices:
                print("  REE API失败，尝试其他API...")
                prices = fetch_from_api(date)
            
            # 如果所有API都失败，尝试从HTML解析
            if not prices:
                print("  所有API失败，尝试从HTML解析...")
                prices = fetch_from_html(date)
            
            if prices:
                data[date_str] = prices
                updated = True
                print(f"✓ {date_str} 数据获取成功")
            else:
                print(f"✗ {date_str} 数据获取失败")
    
    if updated:
        # 只保留最近10天的数据
        cutoff_date = today - timedelta(days=9)
        cutoff_str = format_date(cutoff_date)
        data = {k: v for k, v in data.items() if k >= cutoff_str}
        
        save_pvpc_data(data)
        print("✓ 数据已保存到 pvpc.json")
    else:
        print("✗ 没有获取到新数据")
    
    return data

if __name__ == '__main__':
    update_pvpc_data()
