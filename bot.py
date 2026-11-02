import telebot
from telebot import types
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
import requests
import time
import re
import os
import threading
import phonenumbers
import pycountry

# ==================== CONFIGURATION ====================
BOT_TOKEN = "9249529212:AAGvubFY61S-ePYd8uMr1zDLntVhmRfLrpo"
OWNER_ID = 8523774444

API_BASE_URL = "https://augestel.com/api/v1/iprn"
API_KEY = "sk_live_lAYP9reVGmr3wHVcsJ3AOIBqjGMtiErHc959Ngeo"

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

admin_temp_state = {}

def load_stock_dict():
    if not os.path.exists(STOCK_FILE):
        return {}
    stock_dict = {}
    with open(STOCK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            num = parts[0].replace("+", "").strip()
            srv = parts[1].upper().strip() if len(parts) > 1 else "OTP"
            
            _, c_code, _ = get_country_info(num)
            
            if srv not in stock_dict:
                stock_dict[srv] = {}
            if c_code not in stock_dict[srv]:
                stock_dict[srv][c_code] = []
            if num not in stock_dict[srv][c_code]:
                stock_dict[srv][c_code].append(num)
    return stock_dict

def save_stock_dict(stock_dict):
    def _write():
        with open(STOCK_FILE, "w", encoding="utf-8") as f:
            for srv, countries in stock_dict.items():
                for c_code, nums in countries.items():
                    for num in nums:
                        f.write(f"+{num}|{srv}\n")
    threading.Thread(target=_write, daemon=True).start()

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

stock_data = load_stock_dict()
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

def get_country_info(number_str):
    try:
        clean = re.sub(r'\D', '', number_str)
        if not number_str.startswith('+'):
            number_str = "+" + clean
            
        parsed = phonenumbers.parse(number_str)
        country_code = phonenumbers.region_code_for_number(parsed)
        
        if country_code:
            country = pycountry.countries.get(alpha_2=country_code)
            country_name = country.name.upper() if country else "GLOBAL"
            flag = "".join(chr(127397 + ord(c)) for c in country_code.upper())
            return flag, country_code, country_name
        else:
            return "🌐", "GLOBAL", "GLOBAL"
    except Exception:
        return "🌐", "GLOBAL", "GLOBAL"

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
    try:
        bot.send_message(TARGET_GROUP_ID, "🚀 OTP Group Bot Started & Connected Successfully!")
        print("✅ Telegram Group Connection: SUCCESS")
    except Exception as e:
        print(f"❌ Telegram Group Connection: FAILED -> {e}")

    headers = {'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'}
    try:
        res = http_session.get(f"{API_BASE_URL}/messages", headers=headers, params={'per_page': 1}, timeout=15)
        print(f"📡 API Status Code: {res.status_code}")
        if res.status_code == 200:
            print("✅ Augestel API Connection: SUCCESS")
        else:
            print(f"❌ Augestel API Connection: FAILED (Code: {res.status_code})")
    except Exception as e:
        print(f"❌ Augestel API Connection: FAILED -> {e}")
    print("=" * 50)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📱 Get Number", "📊 Stats")
    if is_admin(message.chat.id):
        markup.add("➕ Add Number", "🗑 Delete Number", "📂 Get No-OTP File")
    bot.send_message(message.chat.id, "⚡ OTP Group Bot Active!", reply_markup=markup)

# ==================== ADMIN: ADD NUMBER VIA FILE ====================
@bot.message_handler(func=lambda m: m.text == "➕ Add Number" and is_admin(m.chat.id))
def add_num_prompt(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(text="📱 WHATSAPP", callback_data="addsrv_WHATSAPP"),
        InlineKeyboardButton(text="📱 TELEGRAM", callback_data="addsrv_TELEGRAM")
    )
    markup.add(
        InlineKeyboardButton(text="📱 INSTAGRAM", callback_data="addsrv_INSTAGRAM"),
        InlineKeyboardButton(text="📱 OTHER (OTP)", callback_data="addsrv_OTP")
    )
    bot.send_message(message.chat.id, "👇 প্রথমে কোন সার্ভিসের জন্য নাম্বার এড করবেন তা সিলেক্ট করুন:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("addsrv_"))
def callback_add_service(call):
    bot.answer_callback_query(call.id)
    srv = call.data.split("_")[1]
    admin_temp_state[call.message.chat.id] = {"action": "adding", "service": srv}
    bot.edit_message_text(
        f"🎯 Selected Service: <b>{srv}</b>\n\n📁 এখন এই সার্ভিসের নাম্বারযুক্ত একটি <b>.txt ফাইল</b> চ্যাট বক্সে আপলোড করুন।",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML"
    )

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not is_admin(message.chat.id):
        return
    state = admin_temp_state.get(message.chat.id)
    if not state or state.get("action") != "adding":
        return
    
    srv = state.get("service", "OTP")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_text = downloaded_file.decode('utf-8')
        
        lines = file_text.split("\n")
        added_count = 0
        sample_num = ""
        
        for line in lines:
            clean_nums = re.findall(r'\d{8,15}', line)
            if clean_nums:
                num = clean_nums[0]
                if not sample_num:
                    sample_num = num
                
                flag, c_code, _ = get_country_info(num)
                if srv not in stock_data:
                    stock_data[srv] = {}
                if c_code not in stock_data[srv]:
                    stock_data[srv][c_code] = []
                
                if num not in used_numbers and num not in stock_data[srv][c_code]:
                    stock_data[srv][c_code].append(num)
                    added_count += 1

        save_stock_dict(stock_data)
        del admin_temp_state[message.chat.id]
        
        bot.send_message(message.chat.id, f"✅ সফলভাবে {added_count} টি নাম্বার {srv} সার্ভিসে স্টকে যুক্ত করা হয়েছে!")

        if added_count > 0 and sample_num:
            flag, c_code, c_name = get_country_info(sample_num)
            srv_emoji = "💚" if srv == "WHATSAPP" else ("💙" if srv == "TELEGRAM" else "💜")
            group_post = (
                f"➖➖➖➖➖➖➖➖\n"
                f"🆕 《 **NEW NUMBERS** 》\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"{flag} **{c_name}** {srv_emoji} **{srv}**\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"📤 **Total Added:** {added_count} ✅\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"🚀 **Use bot link to get your numbers!** 👉"
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🤖 Open OTP Group Bot", url=BOT_USERNAME))
            try:
                bot.send_message(TARGET_GROUP_ID, group_post, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                print(f"Group stock post error: {e}")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ফাইল প্রসেস করতে সমস্যা হয়েছে: {e}")

# ==================== ADMIN: DELETE NUMBER ====================
@bot.message_handler(func=lambda m: m.text == "🗑 Delete Number" and is_admin(m.chat.id))
def delete_num_prompt(message):
    markup = InlineKeyboardMarkup()
    for srv in stock_data.keys():
        if stock_data[srv]:
            markup.add(InlineKeyboardButton(text=f"🗑 Delete from {srv}", callback_data=f"delsrv_{srv}"))
    if not markup.keyboard:
        bot.send_message(message.chat.id, "⚠️ ডিলিট করার মতো কোনো স্টক নেই!")
        return
    bot.send_message(message.chat.id, "👇 কোন সার্ভিসের স্টক থেকে নাম্বার ডিলিট করতে চান তা সিলেক্ট করুন:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delsrv_"))
def callback_del_service(call):
    bot.answer_callback_query(call.id)
    srv = call.data.split("_")[1]
    countries = stock_data.get(srv, {})
    
    markup = InlineKeyboardMarkup()
    for c_code in countries.keys():
        if countries[c_code]:
            sample_num = countries[c_code][0]
            flag, _, c_name = get_country_info(sample_num)
            count = len(countries[c_code])
            markup.add(InlineKeyboardButton(text=f"{flag} {c_name} ({count} pcs)", callback_data=f"delcountry_{srv}_{c_code}"))
    
    markup.add(InlineKeyboardButton(text="🔙 Back", callback_data="back_to_delsrv"))
    bot.edit_message_text(f"🎯 Service: <b>{srv}</b>\n👇 কোন দেশের নাম্বার ডিলিট করতে চান সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delcountry_"))
def callback_del_country(call):
    bot.answer_callback_query(call.id)
    parts = call.data.split("_")
    srv, c_code = parts[1], parts[2]
    
    if srv in stock_data and c_code in stock_data[srv]:
        count = len(stock_data[srv][c_code])
        stock_data[srv][c_code] = []
        save_stock_dict(stock_data)
        bot.edit_message_text(f"✅ {srv} সার্ভিসের {c_code} দেশের সমস্ত ({count}টি) নাম্বার সফলভাবে ডিলিট করা হয়েছে!", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_delsrv")
def callback_back_delsrv(call):
    bot.answer_callback_query(call.id)
    delete_num_prompt(call.message)

# ==================== USER: GET NUMBER FLOW ====================
@bot.message_handler(func=lambda m: m.text == "📱 Get Number")
def get_number_handler(message):
    markup = InlineKeyboardMarkup()
    has_stock = False
    for srv, countries in stock_data.items():
        total_srv_stock = sum(len(nums) for nums in countries.values())
        if total_srv_stock > 0:
            has_stock = True
            markup.add(InlineKeyboardButton(text=f"📱 {srv} (Stock: {total_srv_stock})", callback_data=f"get_srv_{srv}"))
    
    if not has_stock:
        bot.send_message(message.chat.id, "⚠️ বর্তমানে কোনো সার্ভিকেই পর্যাপ্ত স্টক নেই!")
        return
    bot.send_message(message.chat.id, "👇 যে সার্ভিসের জন্য নাম্বার নিতে চান তা সিলেক্ট করুন:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("get_srv_"))
def callback_get_service(call):
    bot.answer_callback_query(call.id)
    srv = call.data.split("_")[2]
    countries = stock_data.get(srv, {})
    
    markup = InlineKeyboardMarkup()
    for c_code, nums in countries.items():
        if len(nums) > 0:
            flag, _, c_name = get_country_info(nums[0])
            markup.add(InlineKeyboardButton(text=f"{flag} {c_name} (Stock: {len(nums)})", callback_data=f"get_country_{srv}_{c_code}"))
            
    markup.add(InlineKeyboardButton(text="🔙 Back", callback_data="back_to_services"))
    bot.edit_message_text(f"🎯 Service: <b>{srv}</b>\n👇 কোন দেশের নাম্বার নিতে চান সিলেক্ট করুন:", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("get_country_"))
def callback_get_country_panel(call):
    bot.answer_callback_query(call.id)
    parts = call.data.split("_")
    srv, c_code = parts[2], parts[3]
    send_number_panel(call.message.chat.id, edit_message_id=call.message.message_id, selected_service=srv, selected_country=c_code)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_services")
def callback_back_services(call):
    bot.answer_callback_query(call.id)
    get_number_handler(call.message)

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
    total_stock = sum(len(nums) for countries in stock_data.values() for nums in countries.values())
    text = f"📊 <b>Bot Stats:</b>\n\n📦 Total Stock: {total_stock}\n✅ OTP Received: {len(used_numbers)}\n❌ No OTP: {len(no_otp_numbers)}"
    bot.send_message(message.chat.id, text, parse_mode="HTML")

def build_assignment_keyboard(num1, service1, otp1, num2, service2, otp2):
    markup = InlineKeyboardMarkup()
    
    btn_num1 = InlineKeyboardButton(text=f"+{num1}", copy_text=CopyTextButton(text=f"+{num1}"))
    text_otp1 = f"🟢 [{service1}] {otp1}" if otp1 else f"⏳ Waiting..."
    copy_val_1 = str(otp1) if otp1 else "Waiting"
    btn_otp1 = InlineKeyboardButton(text=text_otp1, copy_text=CopyTextButton(text=copy_val_1))
    
    btn_num2 = InlineKeyboardButton(text=f"+{num2}", copy_text=CopyTextButton(text=f"+{num2}"))
    text_otp2 = f"🟢 [{service2}] {otp2}" if otp2 else f"⏳ Waiting..."
    copy_val_2 = str(otp2) if otp2 else "Waiting"
    btn_otp2 = InlineKeyboardButton(text=text_otp2, copy_text=CopyTextButton(text=copy_val_2))
    
    btn_bot = InlineKeyboardButton(text="OTP Group Bot", url=BOT_USERNAME)
    btn_channel = InlineKeyboardButton(text="Main Channel", url="https://t.me/facboo578")
    btn_change = InlineKeyboardButton(text="🔄 Change Number", callback_data="change_number_act")
    
    markup.add(btn_num1)
    markup.add(btn_otp1)
    markup.add(btn_num2)
    markup.add(btn_otp2)
    markup.add(btn_bot, btn_channel)
    markup.add(btn_change)
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "change_number_act")
def callback_change_number(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    target_srv = "OTP"
    target_country = None
    for num, info in list(active_assignments.items()):
        if info["chat_id"] == chat_id and info["message_id"] == msg_id:
            historical_assignments[num] = info
            target_srv = info.get("service", "OTP")
            target_country = info.get("country")
            
    if target_country and target_srv in stock_data and target_country in stock_data[target_srv]:
        send_number_panel(chat_id, edit_message_id=msg_id, selected_service=target_srv, selected_country=target_country)
    else:
        get_number_handler(call.message)

def send_number_panel(chat_id, edit_message_id=None, selected_service="OTP", selected_country=None):
    global stock_data
    if not selected_country or len(stock_data.get(selected_service, {}).get(selected_country, [])) < 2:
        msg_text = f"⚠️ এই দেশে পর্যাপ্ত নম্বর নেই!"
        if edit_message_id:
            try: bot.edit_message_text(msg_text, chat_id, edit_message_id)
            except: bot.send_message(chat_id, msg_text)
        else:
            bot.send_message(chat_id, msg_text)
        return

    num1 = stock_data[selected_service][selected_country].pop(0)
    num2 = stock_data[selected_service][selected_country].pop(0)
    
    save_stock_dict(stock_data)
    
    total_rem = sum(len(nums) for countries in stock_data.values() for nums in countries.values())
    text = f"📦 <b>Available Stock:</b> {total_rem}\n🎯 <b>Service:</b> {selected_service}\n👇 Copy Number/OTP below:"
    markup = build_assignment_keyboard(num1, selected_service, None, num2, selected_service, None)

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

    active_assignments[num1] = {"chat_id": chat_id, "message_id": msg_id, "slot": 1, "pair": num2, "otp": None, "service": selected_service, "country": selected_country}
    active_assignments[num2] = {"chat_id": chat_id, "message_id": msg_id, "slot": 2, "pair": num1, "otp": None, "service": selected_service, "country": selected_country}

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
            service_short = get_service_short_name(sms_text)
            clean_num = number.replace("+", "")

            if clean_num not in used_numbers:
                used_numbers.add(clean_num)
                append_to_file_safe(USED_FILE, clean_num)
                
            if clean_num in no_otp_numbers:
                no_otp_numbers.remove(clean_num)
                save_list_from_memory(NO_OTP_FILE, list(no_otp_numbers))

            flag, country_code, country_name = get_country_info(clean_num)
            formatted_rabbi_num = format_group_number_with_rabbi(clean_num)
            
            group_msg = f"{flag} #{country_code} 📱 {formatted_rabbi_num} #{country_code}\n💬 [{service_short}] OTP: <code>{otp_code}</code>"
            
            markup = InlineKeyboardMarkup()
            copy_btn = InlineKeyboardButton(text=f"📋 {otp_code}", copy_text=CopyTextButton(text=str(otp_code)))
            btn_bot = InlineKeyboardButton(text="OTP Group Bot", url=BOT_USERNAME)
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
                pair_num = info["pair"]
                srv_name = info.get("service", "OTP")
                
                pair_info = active_assignments.get(pair_num) or historical_assignments.get(pair_num)
                pair_otp = pair_info["otp"] if pair_info else None
                
                n1, o1 = (clean_num, otp_code) if info["slot"] == 1 else (pair_num, pair_otp)
                n2, o2 = (pair_num, pair_otp) if info["slot"] == 1 else (clean_num, otp_code)

                new_markup = build_assignment_keyboard(n1, srv_name, o1, n2, srv_name, o2)
                try:
                    bot.edit_message_reply_markup(chat_id=info["chat_id"], message_id=info["message_id"], reply_markup=new_markup)
                except:
                    pass

            elif clean_num in historical_assignments:
                info = historical_assignments[clean_num]
                info["otp"] = otp_code
                pair_num = info["pair"]
                srv_name = info.get("service", "OTP")
                
                pair_info = active_assignments.get(pair_num) or historical_assignments.get(pair_num)
                pair_otp = pair_info["otp"] if pair_info else None
                
                n1, o1 = (clean_num, otp_code) if info["slot"] == 1 else (pair_num, pair_otp)
                n2, o2 = (pair_num, pair_otp) if info["slot"] == 1 else (clean_num, otp_code)

                new_markup = build_assignment_keyboard(n1, srv_name, o1, n2, srv_name, o2)
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
EOF
