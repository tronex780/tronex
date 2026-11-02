import telebot
from telebot import types
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
import requests
import time
import re
import os
import threading
from datetime import datetime, timezone, timedelta

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8906385956:AAEQ7I3XAXPxYJ-AZXu_vgwKXKTvywnyPRs"
OWNER_ID = 8523774444

# Augestel API Configuration
API_BASE_URL = "https://augestel.com/api/v1/iprn"
API_KEY = "sk_live_lAYP9reVGmr3wHVcsJ3AOIBqjGMtiErHc959Ngeo"

# Telegram Group Chat ID & Bot Username/Link
TARGET_GROUP_ID = "-1002414484554"
BOT_USERNAME = "https://t.me/tronex3_bot"
MAIN_CHANNEL_URL = "https://t.me/facboo578"

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
        return "TELEGRAM"
    elif "instagram" in text_lower or "ig" in text_lower:
        return "INSTAGRAM"
    elif "whatsapp" in text_lower or "wa" in text_lower:
        return "WHATSAPP"
    elif "google" in text_lower or "gmail" in text_lower:
        return "GOOGLE"
    elif "facebook" in text_lower or "fb" in text_lower:
        return "FACEBOOK"
    elif "twitter" in text_lower or "x.com" in text_lower:
        return "TWITTER"
    elif "imo" in text_lower:
        return "IMO"
    else:
        return "WHATSAPP"

# কান্ট্রি কোড ও পতাকা ম্যাপিং
COUNTRY_MAPPING = {
    '93':  ('🇦🇫', 'AFGHANISTAN'),
    '880': ('🇧🇩', 'BANGLADESH'),
    '852': ('🇭🇰', 'HONG KONG'),
    '86':  ('🇨🇳', 'CHINA'),
    '49':  ('🇩🇪', 'GERMANY'),
    '44':  ('🇬🇧', 'UNITED KINGDOM'),
    '1':   ('🇺🇸', 'UNITED STATES'),
    '33':  ('🇫🇷', 'FRANCE'),
    '7':   ('🇷🇺', 'RUSSIA'),
    '91':  ('🇮🇳', 'INDIA'),
    '92':  ('🇵🇰', 'PAKISTAN'),
    '966': ('🇸🇦', 'SAUDI ARABIA'),
    '971': ('🇦🇪', 'UAE'),
    '60':  ('🇲🇾', 'MALAYSIA'),
    '65':  ('🇸🇬', 'SINGAPORE'),
    '62':  ('🇮🇩', 'INDONESIA'),
    '81':  ('🇯🇵', 'JAPAN'),
    '82':  ('🇰🇷', 'SOUTH KOREA'),
    '39':  ('🇮🇹', 'ITALY'),
    '34':  ('🇪🇸', 'SPAIN'),
    '55':  ('🇧🇷', 'BRAZIL'),
    '61':  ('🇦🇺', 'AUSTRALIA'),
}

def get_country_info(number_str):
    clean = re.sub(r'\D', '', number_str)
    for length in [4, 3, 2, 1]:
        if len(clean) >= length:
            prefix = clean[:length]
            if prefix in COUNTRY_MAPPING:
                return COUNTRY_MAPPING[prefix]
    return '🌐', 'INTERNATIONAL'

def format_group_number_with_rabbi(number_str):
    clean = re.sub(r'\D', '', number_str)
    if len(clean) >= 6:
        first_3 = clean[:3]
        last_3 = clean[-3:]
        return f"<b>{first_3}</b>‣RABBI‣<b>{last_3}</b>"
    return f"<b>{clean}</b>"

def send_stock_added_notification(country_flag, country_name, service_name, count):
    msg = (
        f"➖➖➖➖➖➖➖➖\n"
        f"🆕 《 NEW NUMBERS HIGH TRAFIK 🔥》\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"{country_flag} {country_name} 💚 {service_name}\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"📤 Total Added: {count} ✅\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"🚀 Use bot link to get your numbers! 👉"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="নাম্বার বট", url=BOT_USERNAME))
    try:
        bot.send_message(TARGET_GROUP_ID, msg, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print(f"Stock notification error: {e}")

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
    msg = bot.send_message(message.chat.id, "নম্বরগুলোর লিস্টসহ .txt ফাইল পাঠান অথবা মেসেজে টেক্সট আকারে পাঠান:")
    bot.register_next_step_handler(msg, process_add_number)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not is_admin(message.chat.id):
        return
    if message.document.file_name.endswith('.txt'):
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            file_text = downloaded_file.decode('utf-8')
            
            global added_numbers
            raw_nums = re.findall(r'\+?\d{8,15}', file_text)
            added_count = 0
            sample_num = "8801700000000"
            
            for num in raw_nums:
                clean_num = num.replace("+", "")
                if clean_num not in added_numbers and clean_num not in used_numbers:
                    added_numbers.append(clean_num)
                    added_count += 1
                    sample_num = clean_num
                    
            save_list_from_memory(STOCK_FILE, added_numbers)
            
            # কান্ট্রি ডিটেক্ট করে গ্রুপে নির্দিষ্ট ফরম্যাটে নোটিফিকেশন পাঠানো
            flag, country_name = get_country_info(sample_num)
            send_stock_added_notification(flag, country_name, "WHATSAPP", added_count)
            
            bot.send_message(message.chat.id, f"✅ ফাইল থেকে সফলভাবে {added_count} টি নম্বর স্টকে যুক্ত করা হয়েছে!\n📦 মোট স্টক: {len(added_numbers)}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ফাইল প্রসেস করতে সমস্যা হয়েছে: {e}")

def process_add_number(message):
    global added_numbers
    raw_nums = re.findall(r'\+?\d{8,15}', message.text or "")
    added_count = 0
    sample_num = "8801700000000"
    
    for num in raw_nums:
        clean_num = num.replace("+", "")
        if clean_num not in added_numbers and clean_num not in used_numbers:
            added_numbers.append(clean_num)
            added_count += 1
            sample_num = clean_num
            
    save_list_from_memory(STOCK_FILE, added_numbers)
    
    if added_count > 0:
        flag, country_name = get_country_info(sample_num)
        send_stock_added_notification(flag, country_name, "WHATSAPP", added_count)
        
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

def build_assignment_keyboard(num1, otp1, num2, otp2):
    markup = InlineKeyboardMarkup()
    
    btn_num1 = InlineKeyboardButton(text=f"+{num1}", copy_text=CopyTextButton(text=f"+{num1}"))
    text_otp1 = f"📋 {otp1}" if otp1 else "📋 ⏳ Waiting..."
    btn_otp1 = InlineKeyboardButton(text=text_otp1, copy_text=CopyTextButton(text=otp1 if otp1 else "Waiting"))
    
    btn_num2 = InlineKeyboardButton(text=f"+{num2}", copy_text=CopyTextButton(text=f"+{num2}"))
    text_otp2 = f"📋 {otp2}" if otp2 else "📋 ⏳ Waiting..."
    btn_otp2 = InlineKeyboardButton(text=text_otp2, copy_text=CopyTextButton(text=otp2 if otp2 else "Waiting"))
    
    btn_bot = InlineKeyboardButton(text="নাম্বার বট", url=BOT_USERNAME)
    btn_channel = InlineKeyboardButton(text="Main Channel", url=MAIN_CHANNEL_URL)
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
    markup = build_assignment_keyboard(num1, None, num2, None)

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

    active_assignments[num1] = {"chat_id": chat_id, "message_id": msg_id, "slot": 1, "pair": num2, "otp": None}
    active_assignments[num2] = {"chat_id": chat_id, "message_id": msg_id, "slot": 2, "pair": num1, "otp": None}

def fetch_from_augestel_api(is_startup=False):
    url = f"{API_BASE_URL}/messages"
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Accept': 'application/json'
    }
    params = {'per_page': 10, 'page': 1}
    
    try:
        res = http_session.get(url, headers=headers, params=params, timeout=15)
        if res.status_code != 200:
            return
        
        response_data = res.json()
        if not response_data.get("success", False):
            return
            
        records = response_data.get("data", [])
        if isinstance(records, list):
            records.reverse()

        if is_startup:
            records = records[-5:]

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

            flag, country_code = get_country_info(clean_num)
            formatted_rabbi_num = format_group_number_with_rabbi(clean_num)
            
            group_msg = f"{flag} #{country_code} 📱 {formatted_rabbi_num} #{country_code}\n💬 [{service_name}] OTP: <code>{otp_code}</code>"
            
            markup = InlineKeyboardMarkup()
            copy_btn = InlineKeyboardButton(text=f"📋 {otp_code}", copy_text=CopyTextButton(text=str(otp_code)))
            btn_bot = InlineKeyboardButton(text="নাম্বার বট", url=BOT_USERNAME)
            btn_channel = InlineKeyboardButton(text="Main Channel", url=MAIN_CHANNEL_URL)
            
            markup.add(copy_btn)
            markup.add(btn_bot, btn_channel)

            if not is_startup:
                try:
                    bot.send_message(TARGET_GROUP_ID, group_msg, parse_mode="HTML", reply_markup=markup)
                except Exception as e:
                    print(f"Group send error: {e}")

            if clean_num in active_assignments or clean_num in historical_assignments:
                info = active_assignments.get(clean_num) or historical_assignments.get(clean_num)
                info["otp"] = otp_code
                pair_num = info["pair"]
                
                pair_info = active_assignments.get(pair_num) or historical_assignments.get(pair_num)
                pair_otp = pair_info["otp"] if pair_info else None
                
                n1, o1 = (clean_num, otp_code) if info["slot"] == 1 else (pair_num, pair_otp)
                n2, o2 = (pair_num, pair_otp) if info["slot"] == 1 else (clean_num, otp_code)

                new_markup = build_assignment_keyboard(n1, o1, n2, o2)
                try:
                    bot.edit_message_reply_markup(chat_id=info["chat_id"], message_id=info["message_id"], reply_markup=new_markup)
                except:
                    pass

            processed_ids.add(unique_id)

    except Exception as e:
        print(f"API fetch error: {e}")

def background_worker():
    fetch_from_augestel_api(is_startup=True)
    print("🚀 Bot started and processed last 5 old OTPs successfully!")
    while True:
        fetch_from_augestel_api(is_startup=False)
        if len(processed_ids) > 6000:
            processed_ids.clear()
        time.sleep(20)

if __name__ == "__main__":
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()
    bot.infinity_polling()
