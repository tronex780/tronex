import telebot
from telebot import types
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
import requests
import time
import re
import os
import threading

# ==================== CONFIGURATION ====================
BOT_TOKEN = "9249529212:AAGvubFY61S-ePYd8uMr1zDLntVhmRfLrpo"
OWNER_ID = 8523774444

# Augestel API Configuration (Working Key)
API_BASE_URL = "https://augestel.com/api/v1/iprn"
API_KEY = "sk_live_lAYP9reVGmr3wHVcsJ3AOIBqjGMtiErHc959Ngeo"

# Telegram Group Chat ID & Bot Username
TARGET_GROUP_ID = "-1002414484554"
BOT_USERNAME = "https://t.me/Hong_Kong_TG_bot"

STOCK_FILE = "stock_numbers.txt"
USED_FILE = "used_numbers.txt"
NO_OTP_FILE = "no_otp_numbers.txt"

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=25)

http_session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)

def load_list_from_file(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def append_to_file_safe(filepath, item):
    def _write():
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"{item}\n")
    threading.Thread(target=_write, daemon=True).start()

def save_list_from_memory(filepath, items):
    def _write():
        with open(filepath, "w", encoding="utf-8") as f:
            for item in items:
                f.write(f"{item}\n")
    threading.Thread(target=_write, daemon=True).start()

added_numbers = load_list_from_file(STOCK_FILE)
used_numbers = set(load_list_from_file(USED_FILE))
no_otp_numbers = set(load_list_from_file(NO_OTP_FILE))

active_assignments = {} 
historical_assignments = {} 
processed_ids = set()

def is_admin(user_id):
    return user_id == OWNER_ID

def extract_otp(message):
    match = re.search(r'\b\d{4,8}\b|\b\d{3}-\d{3}\b', message)
    if match:
        return match.group(0)
    return "N/A"

def get_service_short_name(message_text):
    text_lower = message_text.lower()
    if "telegram" in text_lower or "tg" in text_lower:
        return "TG"
    elif "instagram" in text_lower or "ig" in text_lower:
        return "IG"
    elif "whatsapp" in text_lower or "wa" in text_lower:
        return "WA"
    elif "google" in text_lower or "gmail" in text_lower:
        return "GG"
    elif "facebook" in text_lower or "fb" in text_lower:
        return "FB"
    elif "twitter" in text_lower or "x.com" in text_lower:
        return "X"
    elif "imo" in text_lower:
        return "IMO"
    elif "line" in text_lower:
        return "LINE"
    else:
        return "OTP"

# ডায়নামিক কান্ট্রি কোড ও ফ্ল্যাগ ডিটেকশন ম্যাপ (বড় কান্ট্রি কোডগুলো আগে চেক হবে)
COUNTRY_MAPPING = {
    '880': ('🇧🇩', 'BD'),
    '852': ('🇭🇰', 'HK'),
    '86':  ('🇨🇳', 'CN'),
    '49':  ('🇩🇪', 'DE'),
    '44':  ('🇬🇧', 'UK'),
    '1':   ('🇺🇸', 'US'),
    '33':  ('🇫🇷', 'FR'),
    '7':   ('🇷🇺', 'RU'),
    '91':  ('🇮🇳', 'IN'),
    '92':  ('🇵🇰', 'PK'),
    '966': ('🇸🇦', 'SA'),
    '971': ('🇦🇪', 'AE'),
    '60':  ('🇲🇾', 'MY'),
    '65':  ('🇸🇬', 'SG'),
    '62':  ('🇮🇩', 'ID'),
    '81':  ('🇯🇵', 'JP'),
    '82':  ('🇰🇷', 'KR'),
    '39':  ('🇮🇹', 'IT'),
    '34':  ('🇪🇸', 'ES'),
    '55':  ('🇧🇷', 'BR'),
    '61':  ('🇦🇺', 'AU'),
    '20':  ('🇪🇬', 'EG'),
    '90':  ('🇹🇷', 'TR'),
    '84':  ('🇻🇳', 'VN'),
    '66':  ('🇹🇭', 'TH'),
}

def get_country_info(number_str):
    clean = re.sub(r'\D', '', number_str)
    # প্রথমে ৪, ৩ এবং ২ ডিজিটের প্রিফিক্সগুলো মিলিয়ে দেখবে
    for length in [4, 3, 2, 1]:
        if len(clean) >= length:
            prefix = clean[:length]
            if prefix in COUNTRY_MAPPING:
                return COUNTRY_MAPPING[prefix]
    
    prefix = clean[:3] if len(clean) >= 3 else clean
    return "🌐", prefix

def format_group_number_with_rabbi(number_str):
    clean = re.sub(r'\D', '', number_str)
    if len(clean) >= 6:
        first_3 = clean[:3]
        last_3 = clean[-3:]
        return f"<b>{first_3}</b>‣RABBI‣<b>{last_3}</b>"
    return f"<b>{clean}</b>"

def run_startup_tests():
    print("=" * 50)
    print("🔍 Running Bot Startup Diagnostics...")
    
    tg_success = False
    for attempt in range(3):
        try:
            bot.send_message(TARGET_GROUP_ID, "🚀 Hong Kong Bot Started & Connected Successfully!")
            print("✅ Telegram Group Connection: SUCCESS")
            tg_success = True
            break
        except Exception as e:
            print(f"⚠️ Telegram Attempt {attempt+1} Failed: {e}")
            time.sleep(3)
    if not tg_success:
        print("❌ Telegram Group Connection: FAILED after 3 attempts.")

    headers = {'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'}
    api_success = False
    for attempt in range(3):
        try:
            res = http_session.get(f"{API_BASE_URL}/messages", headers=headers, params={'per_page': 1}, timeout=15)
            print(f"📡 API Status Code: {res.status_code}")
            if res.status_code == 200:
                print("✅ Augestel API Connection: SUCCESS")
                api_success = True
                break
            else:
                print(f"⚠️ API Attempt {attempt+1} Code: {res.status_code}")
        except Exception as e:
            print(f"⚠️ API Attempt {attempt+1} Failed -> {e}")
        time.sleep(3)
    if not api_success:
        print("❌ Augestel API Connection: FAILED after 3 attempts.")
    print("=" * 50)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📱 Get Number", "📊 Stats")
    if is_admin(message.chat.id):
        markup.add("➕ Add Number", "🗑 Delete Number")
        markup.add("📂 Get No-OTP File")
    bot.send_message(message.chat.id, "⚡ Hong Kong OTP Bot Active (Safe Stock Mode)!", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🗑 Delete Number" and is_admin(m.chat.id))
def delete_all_stock_numbers(message):
    global added_numbers
    count = len(added_numbers)
    added_numbers.clear()
    save_list_from_memory(STOCK_FILE, added_numbers)
    bot.send_message(message.chat.id, f"🗑 মোট {count} টি স্টক নম্বর সফলভাবে মুছে ফেলা হয়েছে!")

@bot.message_handler(func=lambda m: m.text == "➕ Add Number" and is_admin(m.chat.id))
def add_num_prompt(message):
    msg = bot.send_message(message.chat.id, "নম্বরগুলো এক বা একাধিক লাইনে / টেক্সট আকারে পাঠান:")
    bot.register_next_step_handler(msg, process_add_number)

def process_add_number(message):
    global added_numbers
    raw_nums = re.findall(r'\+?\d{8,15}', message.text or "")
    added_count = 0
    for num in raw_nums:
        clean_num = num.replace("+", "")
        if clean_num not in added_numbers and clean_num not in used_numbers:
            added_numbers.append(clean_num)
            added_count += 1
    save_list_from_memory(STOCK_FILE, added_numbers)
    bot.send_message(message.chat.id, f"✅ সফলভাবে {added_count} টি নম্বর স্টকে যুক্ত করা হয়েছে!\n📦 মোট স্টক: {len(added_numbers)}")

@bot.message_handler(func=lambda m: m.text == "📂 Get No-OTP File" and is_admin(m.chat.id))
def export_no_otp_file(message):
    if not no_otp_numbers:
        bot.send_message(message.chat.id, "⚠️ No-OTP লিস্ট খালি!")
        return
    with open("no_otp_export.txt", "w", encoding="utf-8") as f:
        for num in no_otp_numbers:
            f.write(f"+{num}\n")
    with open("no_otp_export.txt", "rb") as f:
        bot.send_document(message.chat.id, f, caption=f"📄 No-OTP List (Total: {len(no_otp_numbers)})")

@bot.message_handler(func=lambda m: m.text == "📊 Stats")
def show_stats(message):
    text = (
        f"📊 <b>Bot Stats:</b>\n\n"
        f"📦 Stock: {len(added_numbers)}\n"
        f"✅ OTP Received: {len(used_numbers)}\n"
        f"❌ No OTP: {len(no_otp_numbers)}"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML")

def build_assignment_keyboard(num1, service1, otp1, num2, service2, otp2):
    markup = InlineKeyboardMarkup()
    
    btn_num1 = InlineKeyboardButton(text=f"+{num1}", copy_text=CopyTextButton(text=f"+{num1}"))
    text_otp1 = f"📋 {otp1}" if otp1 else "📋 ⏳ Waiting..."
    btn_otp1 = InlineKeyboardButton(text=text_otp1, copy_text=CopyTextButton(text=otp1 if otp1 else "Waiting"))
    
    btn_num2 = InlineKeyboardButton(text=f"+{num2}", copy_text=CopyTextButton(text=f"+{num2}"))
    text_otp2 = f"📋 {otp2}" if otp2 else "📋 ⏳ Waiting..."
    btn_otp2 = InlineKeyboardButton(text=text_otp2, copy_text=CopyTextButton(text=otp2 if otp2 else "Waiting"))
    
    btn_bot = InlineKeyboardButton(text="Number Bot", url="https://t.me/Hong_Kong_TG_bot")
    btn_channel = InlineKeyboardButton(text="Main Channel", url="https://t.me/facboo578")
    btn_change = InlineKeyboardButton(text="🔄 Change Number", callback_data="change_number_act")
    
    markup.add(btn_num1)
    markup.add(btn_otp1)
    markup.add(btn_num2)
    markup.add(btn_otp2)
    markup.add(btn_bot, btn_channel)
    markup.add(btn_change)
    return markup

@bot.message_handler(func=lambda m: m.text == "📱 Get Number")
def get_number_handler(message):
    send_number_panel(message.chat.id, edit_message_id=None)

@bot.callback_query_handler(func=lambda call: call.data == "change_number_act")
def callback_change_number(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    for num, info in list(active_assignments.items()):
        if info["chat_id"] == chat_id and info["message_id"] == msg_id:
            historical_assignments[num] = info
            
    send_number_panel(chat_id, edit_message_id=msg_id)

def send_number_panel(chat_id, edit_message_id=None):
    global added_numbers
    if len(added_numbers) < 2:
        msg_text = f"⚠️ পর্যাপ্ত নম্বর নেই!\n📦 বর্তমান স্টক: {len(added_numbers)} টি।"
        if edit_message_id:
            try: bot.edit_message_text(msg_text, chat_id, edit_message_id)
            except: bot.send_message(chat_id, msg_text)
        else:
            bot.send_message(chat_id, msg_text)
        return

    num1 = added_numbers.pop(0)
    num2 = added_numbers.pop(0)
    
    save_list_from_memory(STOCK_FILE, added_numbers)
    
    text = f"📦 <b>Available Stock:</b> {len(added_numbers)}\n👇 Copy Number/OTP below:"
    markup = build_assignment_keyboard(num1, "OTP", None, num2, "OTP", None)

    if edit_message_id:
        try:
            sent_msg = bot.edit_message_text(text, chat_id, edit_message_id, parse_mode="HTML", reply_markup=markup)
            msg_id = edit_message_id
        except:
            sent_msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
            msg_id = sent_msg.message_id
    else:
        sent_msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        msg_id = sent_msg.message_id

    active_assignments[num1] = {"chat_id": chat_id, "message_id": msg_id, "slot": 1, "pair": num2, "otp": None, "service": "OTP"}
    active_assignments[num2] = {"chat_id": chat_id, "message_id": msg_id, "slot": 2, "pair": num1, "otp": None, "service": "OTP"}

def fetch_from_augestel_api():
    url = f"{API_BASE_URL}/messages"
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Accept': 'application/json'
    }
    params = {'per_page': 5, 'page': 1}
    
    try:
        res = http_session.get(url, headers=headers, params=params, timeout=15)
        
        if res.status_code == 429:
            retry_after = int(res.headers.get("Retry-After", 20))
            print(f"⚠️ Rate limit hit (429). Pausing for {retry_after} seconds...")
            time.sleep(retry_after)
            return

        if res.status_code != 200:
            return
        
        response_data = res.json()
        if not response_data.get("success", False):
            return
            
        records = response_data.get("data", [])
        if isinstance(records, list):
            records.reverse()

        for item in records:
            if not isinstance(item, dict):
                continue

            number = str(item.get('number', ''))
            sms_text = item.get('message', '')
            received_at = item.get('received_at', '')

            unique_id = f"{number}_{received_at}_{sms_text}"
            if unique_id in processed_ids:
                continue

            otp_code = extract_otp(sms_text)
            service_name = get_service_short_name(sms_text)
            clean_num = number.replace("+", "")

            if clean_num not in used_numbers:
                used_numbers.add(clean_num)
                append_to_file_safe(USED_FILE, clean_num)
                
            if clean_num in no_otp_numbers:
                no_otp_numbers.remove(clean_num)
                save_list_from_memory(NO_OTP_FILE, list(no_otp_numbers))

            # নম্বর দেখে সঠিক ফ্ল্যাগ ও কান্ট্রি কোড সেট করা
            flag, country_code = get_country_info(clean_num)
            formatted_rabbi_num = format_group_number_with_rabbi(clean_num)
            
            group_msg = f"{flag} #{country_code} 📱 {formatted_rabbi_num} #{country_code}\n💬 [{service_name}] OTP: <code>{otp_code}</code>"
            
            markup = InlineKeyboardMarkup()
            copy_btn = InlineKeyboardButton(text=f"📋 {otp_code}", copy_text=CopyTextButton(text=str(otp_code)))
            btn_bot = InlineKeyboardButton(text="Number Bot", url=BOT_USERNAME)
            btn_channel = InlineKeyboardButton(text="Main Channel", url="https://t.me/facboo578")
            
            markup.add(copy_btn)
            markup.add(btn_bot, btn_channel)

            try:
                bot.send_message(TARGET_GROUP_ID, group_msg, parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"Group send error: {e}")

            if clean_num in active_assignments:
                info = active_assignments[clean_num]
                info["otp"] = otp_code
                info["service"] = service_name
                pair_num = info["pair"]
                
                pair_info = active_assignments.get(pair_num) or historical_assignments.get(pair_num)
                pair_otp = pair_info["otp"] if pair_info else None
                pair_srv = pair_info["service"] if pair_info else "OTP"
                
                n1, s1, o1 = (clean_num, service_name, otp_code) if info["slot"] == 1 else (pair_num, pair_srv, pair_otp)
                n2, s2, o2 = (pair_num, pair_srv, pair_otp) if info["slot"] == 1 else (clean_num, service_name, otp_code)

                new_markup = build_assignment_keyboard(n1, s1, o1, n2, s2, o2)
                try:
                    bot.edit_message_reply_markup(chat_id=info["chat_id"], message_id=info["message_id"], reply_markup=new_markup)
                except:
                    pass

            elif clean_num in historical_assignments:
                info = historical_assignments[clean_num]
                info["otp"] = otp_code
                info["service"] = service_name
                pair_num = info["pair"]
                
                pair_info = active_assignments.get(pair_num) or historical_assignments.get(pair_num)
                pair_otp = pair_info["otp"] if pair_info else None
                pair_srv = pair_info["service"] if pair_info else "OTP"
                
                n1, s1, o1 = (clean_num, service_name, otp_code) if info["slot"] == 1 else (pair_num, pair_srv, pair_otp)
                n2, s2, o2 = (pair_num, pair_srv, pair_otp) if info["slot"] == 1 else (clean_num, service_name, otp_code)

                new_markup = build_assignment_keyboard(n1, s1, o1, n2, s2, o2)
                try:
                    bot.edit_message_reply_markup(chat_id=info["chat_id"], message_id=info["message_id"], reply_markup=new_markup)
                except:
                    pass

            processed_ids.add(unique_id)

    except Exception as e:
        print(f"API fetch error: {e}")

def background_worker():
    time.sleep(5)
    while True:
        fetch_from_augestel_api()
        if len(processed_ids) > 6000:
            processed_ids.clear()
        time.sleep(20)

if __name__ == "__main__":
    run_startup_tests()
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    bot.infinity_polling()
