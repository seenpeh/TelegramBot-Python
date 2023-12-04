import json
import sqlite3
import telegram
import api
import datetime
import qrcode
import time
import re
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, constants
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

admin_started = False
db_address = "users.db"
st_address = 'settings.json'

CUSTOMER, SELLER = range(2)
NEW, RENEW, GIFT, LIMITED, INACTIVE = range(5)

token = "6208707573:AAH8JwXbcDJ3ZrUwcJDDBITmyjs5TK_FUTk"  # TEST

settings = {}
admin_id = 0
channel = ''
support = ''
custom_sellers = {}
banned_users = []
discounts = []
active = True
testing = False


# region TOOLS


def load_settings():
    global token, settings, admin_id, channel, support, custom_sellers, banned_users, discounts
    with open('settings.json', 'r', encoding="utf-8") as file:
        settings = json.load(file)
        token = settings['token']
        admin_id = settings['admin']
        channel = settings['channel']
        support = settings['support']
        custom_sellers = settings['custom_sellers']
        banned_users = settings['banned_users']
        discounts = settings['discounts']
        if api.load_settings():
            return True
        else:
            return False


if load_settings():
    application = Application.builder().token(token).build()
else:
    print("couldn't read settings.json")
    exit()


async def remove_handlers(context):
    try:
        if 'query' in context.user_data:
            q = context.user_data['query']
            if q.message is not None:
                await q.edit_message_text("عملیات متوقف شد")
            del context.user_data['query']
        if 'state' in context.user_data:
            del context.user_data['state']
        if 'config' in context.user_data:
            del context.user_data['config']
    except:
        pass


# endregion


# region DAILY CONFIGS CHECK

async def callback_alarm(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT id FROM 'users'")
    rows = c.fetchall()
    conn.close()
    for row in rows:
        _id = row[0]
        try:
            await daily_check(_id)
        except:
            pass
    await application.bot.send_message(chat_id=admin_id, text=f"بررسی کامل کاربران انجام شد ✅")


async def callback_daily(context: ContextTypes.DEFAULT_TYPE):
    context.job_queue.run_daily(callback_alarm, time=datetime.time(hour=18), chat_id=context.user_data['id'])


async def daily_check(target_id):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT cf_name,cf_status FROM 'configs' WHERE cr_id = {target_id}")
    configs = c.fetchall()
    for config in configs:
        cf_name = config[0]
        cf_status = int(config[1])
        data = await api.get_user(cf_name)
        if data:
            enable = data.get("status")
            cf_expire = data.get("expire")
            remain = data.get("remain")
            if not enable:
                if not cf_status == INACTIVE:
                    c.execute(f"UPDATE 'configs' SET cf_status = {INACTIVE} WHERE cf_name = '{cf_name}'")
                    conn.commit()
                    try:
                        await application.bot.send_message(chat_id=target_id,
                                                           text=f"کانفیک {cf_name} غیرفعال شده است ❌️")
                    except:
                        continue
                else:
                    if -7 >= cf_expire:
                        await api.delete_user(cf_name)
                        c.execute(f"DELETE FROM 'configs' WHERE cf_name = '{cf_name}'")
                        conn.commit()
                        try:
                            await application.bot.send_message(chat_id=target_id,
                                                               text=f"کانفیک {cf_name} حذف شد 🗑️")
                        except:
                            continue
            else:
                if 3 >= cf_expire >= 0:
                    try:
                        await application.bot.send_message(chat_id=target_id,
                                                           text=f"کمتر از {cf_expire} روز از بسته {cf_name} باقی مانده⚠️")
                    except:
                        continue
                if remain <= 5:
                    try:
                        await application.bot.send_message(chat_id=target_id,
                                                           text=f" از بسته کانفیک {cf_name} کمتر از ۵ گیگ باقی مانده❕")
                    except:
                        continue

        else:
            c.execute(f"DELETE FROM 'configs' WHERE cf_name = '{cf_name}'")
            conn.commit()
            try:
                await application.bot.send_message(chat_id=target_id, text=f"کانفیک {cf_name} حذف شده است 🗑️")
            except:
                continue
    conn.close()


# endregion


# region MANAGE CONFIGS

async def get_config_status(cf_name):
    data = await api.get_user(cf_name)
    if data:
        if data.get("status"):
            enabled = "روشن 🟢"
        else:
            enabled = "خاموش 🔴"
        expiry = data.get("expire")
        if expiry == 0:
            expiry = "کمتر از یک"
        elif expiry < 0:
            expiry = "0"
        cf_data = data.get("data_limit")
        if round(float(cf_data)) > 100:
            cf_data = "♾️"
        text = "-وضعیت بسته-\n" \
               f"\n✒️نام بسته: {data.get('username')}" \
               f"\n📦حجم بسته: {cf_data} GB" \
               f"\n⬇️حجم استفاده شده: {data.get('used_traffic')} GB" \
               f"\n⌛زمان مانده: {expiry} روز\n" \
               f"\nوضعیت سرویس: {enabled}"

        return text
    else:
        conn = sqlite3.connect(db_address)
        conn.row_factory = lambda cursor, row: row[0]
        c = conn.cursor()
        c.execute(f"DELETE FROM 'configs' WHERE cf_name = '{cf_name}'")
        conn.commit()
        conn.close()


async def list_configs(target_id):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT cf_name FROM 'configs' WHERE cr_id = {target_id}")
    row = c.fetchall()
    if row:
        return row
    conn.close()


async def bind(cf_name, cr_id):
    config = await api.get_user(cf_name)
    user = await get_user_info(cr_id)
    if config is not None and user is not None:
        conn = sqlite3.connect(db_address)
        conn.row_factory = lambda cursor, row: row[0]
        c = conn.cursor()
        c.execute(f"SELECT cr_id FROM configs WHERE cf_name = '{cf_name}';")
        old_cr = c.fetchone()
        if old_cr is None:
            c.execute(f"SELECT name FROM 'users' WHERE id = {cr_id}")
            cr_name = c.fetchone()
            cf_name = config.get('username')
            c.execute(
                """INSERT OR REPLACE INTO configs (cf_name, cf_status, cr_id, cr_name)
                            VALUES (?,?,?,?);""",
                (
                    cf_name,
                    NEW,
                    cr_id,
                    cr_name
                ),
            )
            conn.commit()
            conn.close()
            await application.bot.send_message(chat_id=admin_id,
                                               text=f"کانفیگ {cf_name} به یوزر {cr_id} بایند شد.")
            return f"کانفیگ {cf_name} به لیست سرویس های کاربر اضافه شد."
        else:
            conn.close()
            if old_cr == cr_id:
                return "کانفیگ قبلا به این حساب اضافه شده❕"
            else:
                return "کانفیگ متعلق به کاربر دیگریست❕"
    else:
        return "مشکلی رخ داد❕"


async def unbind(cf_name):
    conn = sqlite3.connect(db_address)
    conn.row_factory = lambda cursor, row: row[0]
    c = conn.cursor()
    c.execute(f"SELECT cf_status FROM 'configs' WHERE cf_name = '{cf_name}'")
    cf_status = int(c.fetchone())
    if cf_status == NEW or cf_status == RENEW:
        c.execute(f"DELETE FROM 'configs' WHERE cf_name = '{cf_name}'")
        conn.commit()
        conn.close()
        return "کانفیگ از لیست شما حذف شد"
    else:
        return "کانفیگ فعال نیست"


# endregion


# region USER MANAGEMENT

async def load_user_data(context: ContextTypes.DEFAULT_TYPE):
    if 'id' in context.user_data:
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"SELECT profit FROM 'users' WHERE id = {context.user_data['id']}")
        row = c.fetchone()
        context.user_data['profit'] = row[0]

        c.execute(f"SELECT balance FROM 'users' WHERE id = {context.user_data['id']}")
        row = c.fetchone()
        context.user_data['balance'] = row[0]

        c.execute(f"SELECT gift FROM 'users' WHERE id = {context.user_data['id']}")
        row = c.fetchone()
        context.user_data['gift'] = row[0]

        c.execute(f"SELECT role FROM 'users' WHERE id = {context.user_data['id']}")
        row = c.fetchone()
        context.user_data['role'] = row[0]

        c.execute(f"SELECT invite FROM 'users' WHERE id = {context.user_data['id']}")
        row = c.fetchone()
        context.user_data['invite'] = row[0]

        # Calculate
        c.execute(
            f"SELECT COUNT(*) FROM 'configs' WHERE cr_id = {context.user_data['id']} AND NOT cf_status = {LIMITED} AND NOT cf_status = {GIFT}")
        row = c.fetchone()
        if row:
            context.user_data['sales'] = row[0]

        c.execute(f"SELECT COUNT(*) FROM 'configs' WHERE cr_id = {context.user_data['id']} AND cf_status = {LIMITED}")
        row = c.fetchone()
        if row:
            context.user_data['limited'] = row[0]

        c.execute(f"SELECT COUNT(*) FROM 'users' WHERE invite = {context.user_data['id']}")
        row = c.fetchone()
        if row:
            context.user_data['invites'] = row[0]

        # Set the multiplier
        if context.user_data['id'] in custom_sellers:
            context.user_data['multiplier'] = 0.3
        elif context.user_data['sales'] + context.user_data['invites'] < 3:
            context.user_data['multiplier'] = 0
        elif context.user_data['sales'] + context.user_data['invites'] < 10:
            context.user_data['multiplier'] = 0.1
        else:
            context.user_data['multiplier'] = 0.2
        conn.close()


async def save_user_data(changes, target_id, override):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    if override:
        for change in changes:
            c.execute(f"UPDATE 'users' SET {change} = {changes[change]} WHERE id = {target_id}")
    else:
        for change in changes:
            c.execute(f"UPDATE 'users' SET {change} = {change} + {changes[change]} WHERE id = {target_id}")
    conn.commit()
    conn.close()


async def check_user_in_the_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not channel == "":
        try:
            user_id = update.effective_user.id
            check = await context.bot.getChatMember('@' + channel, user_id)

            if telegram.ChatMember.MEMBER == check.status or telegram.ChatMember.ADMINISTRATOR == check.status or user_id == admin_id:
                return True
            else:
                return False
        except:
            return True
    else:
        return True


async def save_status():
    with open("settings.json", "r+") as jsonFile:
        data = json.load(jsonFile)

        data["custom_sellers"] = custom_sellers
        data["banned_users"] = banned_users
        data["discounts"] = discounts

        jsonFile.seek(0)  # rewind
        json.dump(data, jsonFile, indent=4, ensure_ascii=False)
        jsonFile.truncate()


async def new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_started
    context.user_data["name"] = update.effective_user.full_name
    context.user_data["username"] = update.effective_user.username
    context.user_data['id'] = update.effective_user.id
    # Readable
    context.user_data["role"] = CUSTOMER
    context.user_data["gift"] = 0
    context.user_data["balance"] = 0
    context.user_data["profit"] = 0
    context.user_data["invite"] = 0
    # Calculative
    context.user_data['limited'] = 0
    context.user_data['invites'] = 0
    context.user_data["multiplier"] = 0
    context.user_data['sales'] = 0
    if admin_started:
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"SELECT * FROM 'users' WHERE id = {context.user_data['id']}")
        if not c.fetchone():
            msg = f"👤New User👤\n" \
                  f"Name: {context.user_data['name']}\n" \
                  f"UserName: @{context.user_data['username']}\n" \
                  f"ID: {context.user_data['id']}"
            await application.bot.send_message(
                chat_id=admin_id, text=msg
            )
            if update.effective_user.id == admin_id:
                context.user_data["role"] = SELLER
            c.execute(
                """INSERT OR IGNORE INTO users (id, name, username, role, balance, profit, gift, invite)
                            VALUES (?,?,?,?,?,?,?,?);""",
                (
                    context.user_data["id"],
                    context.user_data["name"],
                    context.user_data["username"],
                    context.user_data["role"],
                    context.user_data["balance"],
                    context.user_data["profit"],
                    context.user_data["gift"],
                    context.user_data["invite"]
                ),
            )
            conn.commit()
            conn.close()
        await load_user_data(context)

        context.user_data["access"] = True
    elif update.effective_user.id == admin_id:
        admin_started = True
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS users ([id] INTEGER PRIMARY KEY, [name] TEXT, [username] TEXT, 
           [balance] INTEGER, [profit] INTEGER, [gift] INTEGER, [role] INTEGER, [invite] INTEGER)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS configs ([cf_name] TEXT PRIMARY KEY, 
            [cf_status] INTEGER , [cr_id] INTEGER, [cr_name] TEXT)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS logs ([mode] TEXT, [name] TEXT, [data] INTEGER, 
            [price] INTEGER, [cr_id] INTEGER, [cr_name] TEXT, [time] TEXT)"""
        )
        conn.commit()
        conn.close()
        if not context.job_queue.jobs():
            await callback_daily(context)
        await new_user(update, context)


async def get_user_info(cr_id):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT name FROM 'users' WHERE id = {cr_id}")
    result = c.fetchone()
    if result:
        name = result[0]
        c.execute(
            f"SELECT COUNT(*) FROM 'configs' WHERE cr_id = {cr_id} AND NOT cf_status = {LIMITED} AND NOT cf_status = {GIFT}")
        row = c.fetchone()
        if row:
            sales = row[0]
        else:
            sales = 0

        # Set the multiplier
        if cr_id in custom_sellers:
            multiplier = 0.3
        elif sales < 3:
            multiplier = 0
        elif sales < 10:
            multiplier = 0.1
        else:
            multiplier = 0.2
        conn.close()

        return {
            'name': name,
            'multiplier': multiplier,
        }
    else:
        return None


async def get_status(context: ContextTypes.DEFAULT_TYPE):
    if context.user_data['role'] == SELLER:
        role = "فروشنده"
        if context.user_data['id'] == admin_id:
            role = "ادمین"
        text = "-----------پنل ویژه فروشنده🐈‍⬛----------\n\n" \
               f"👤 نام: {context.user_data['name']}\n" \
               f"#️⃣ آیدی: {context.user_data['id']}\n" \
               f"🔒 دسترسی: {role}\n" \
               f"🔗 سرویس های فعال: {context.user_data['sales']}\n" \
               f"🤍 کاربران شما: {context.user_data['invites']}\n" \
               f"📈 ضریب: {context.user_data['multiplier'] * 100}%\n" \
               f"💵 سود: {context.user_data['profit']}\n" \
               f"💰 موجودی: {context.user_data['balance']}\n" \
               f"🎁 حجم هدیه: {context.user_data['gift']}GB"
    else:
        invite = context.user_data['invite']
        if invite == 0:
            promo = "هیچکس"
        else:
            promo = (await get_user_info(invite)).get('name')

        role = "مشتری"
        text = "-----------پنل ویژه مشتری🐈‍⬛----------\n\n" \
               f"👤 نام: {context.user_data['name']}\n" \
               f"#️⃣ آیدی: {context.user_data['id']}\n" \
               f"🔒 دسترسی: {role}\n" \
               f"🔗 سرویس های فعال: {context.user_data['sales']}\n" \
               f"💰 موجودی: {context.user_data['balance']}\n" \
               f"🎁 حجم هدیه: {context.user_data['gift']}GB\n" \
               f"🤝 معرف: {promo}"
    return text


# endregion


# region NEW CONFIG


async def choose_server(context, query):
    keyboard = []
    btn = [InlineKeyboardButton(settings['server']['name'], callback_data="buy")]
    keyboard.append(btn)
    for srv in settings['others']:
        name = srv
        location = settings['others'][srv]
        text = f"{location} | {name}"
        btn = [InlineKeyboardButton(text, url=f"https://t.me/{support}")]
        keyboard.append(btn)
    keyboard.append([InlineKeyboardButton("بازگشت", callback_data="home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="سرور مورد نظر را انتخاب کنید: ", reply_markup=reply_markup
    )


async def buy(context, query):
    if 'config' in context.user_data:
        config = context.user_data['config']
        if config['mode'] == GIFT:
            await confirm(context, query)
        elif config['mode'] == RENEW:
            if not 'expiry' in config:
                await choose_expiry(context, query)
            elif not 'data' in config:
                await choose_data(context, query)
            elif not 'price' in config:
                await choose_price(context, query)
            else:
                await confirm(context, query)
        else:
            if not 'expiry' in config and not config['mode'] == LIMITED:
                await choose_expiry(context, query)
            elif not 'data' in config and not config['mode'] == LIMITED:
                await choose_data(context, query)
            elif not 'price' in config and not config['mode'] == LIMITED:
                await choose_price(context, query)
            elif not 'name' in config:
                await choose_name(context, query)
            else:
                await confirm(context, query)
    else:
        context.user_data['config'] = {'mode': NEW}
        await buy(context, query)


async def choose_expiry(context, query):
    config = context.user_data['config']
    mode = config['mode']
    limits = settings['server']['plans']
    description = settings['server']['description']
    keyboard = []
    for limit in limits:
        text = f"{limit} روزه ⌛"
        btn = [InlineKeyboardButton(text, callback_data=f"expiry={limit}")]
        keyboard.append(btn)
    if mode == NEW and (context.user_data['role'] == SELLER or testing):
        btn = [InlineKeyboardButton("💫 تست سرویس 💫", callback_data="test")]
        keyboard.append(btn)
    keyboard.append([InlineKeyboardButton("بازگشت", callback_data="home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=description, reply_markup=reply_markup
    )


async def choose_data(context, query):
    config = context.user_data['config']
    expiry = config['expiry']
    plans = settings['server']['plans'][expiry]
    keyboard = []
    for plan in plans:
        data = plan.get("data")
        prices = plan.get("prices")
        price = 0
        for price in prices:
            if price > 0:
                break
        if data > 100:
            data_text = "نامحدود"
        else:
            data_text = f"{data} گیگ"
        text = f'{data_text} | 📦 {price} تومان'
        btn = [InlineKeyboardButton(text, callback_data=f"data={data}")]
        keyboard.append(btn)
    keyboard.append([InlineKeyboardButton("بازگشت", callback_data=f"back/expiry")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="پلن مورد نظر را انتخاب کنید: ", reply_markup=reply_markup
    )


async def choose_price(context, query):
    config = context.user_data['config']
    expiry = config['expiry']
    data = config['data']
    plans = settings['server']['plans'][expiry]
    keyboard = []
    for plan in plans:
        if plan.get('data') == data:
            prices = plan.get('prices')
            users = 0
            for price in prices:
                users += 1
                if price > 0:
                    text = f"{price} تومان | 👤 {users} کاربر"
                    btn = [InlineKeyboardButton(text, callback_data=f"price={price}")]
                    keyboard.append(btn)
            break
    keyboard.append([InlineKeyboardButton("بازگشت", callback_data=f"back/data")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "تعداد کاربر مورد نظر را انتخاب کنید: \n"
    await query.edit_message_text(
        text=text, reply_markup=reply_markup
    )


async def choose_name(context, query):
    keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="یک نام برای کانفیگ مورد نظر ارسال کنید:\n"
             "1.حتما از حروف انگیسی استفاده کنید\n"
             "2.از فاصله استفاده نکنید\n"
             "3.نام نباید تکراری باشد",
        reply_markup=reply_markup
    )
    context.user_data['query'] = query
    context.user_data['state'] = 'name'


async def confirm(context, query):
    config = context.user_data['config']

    mode = config.get("mode")

    if 'discount' in config:
        discount = config.get('discount')
    else:
        discount = 0

    if mode == GIFT:
        mode_text = "سرویس هدیه"
        name = f"gift{str(int(time.time()))}"
        expiry = 7
        price = 0
        data = config.get('data')
    elif mode == LIMITED:
        mode_text = "تست سرویس"
        name = config.get("name")
        data = 0.25
        expiry = 1
        price = 0
    elif mode == RENEW:
        mode_text = "تمدید سرویس"
        name = config.get("name")
        data = config.get("data")
        expiry = int(config.get("expiry"))
        price = config.get("price")
    else:
        mode_text = "سرویس جدید"
        name = config.get("name")
        data = config.get("data")
        expiry = int(config.get("expiry"))
        price = config.get("price")

    price = price - (discount * 0.01 * price)

    keyboard = []
    context.user_data['final'] = {
        "mode": mode,
        "name": name,
        "expiry": expiry,
        "data": data,
        "price": price,
        "discount": discount
    }
    keyboard.append([InlineKeyboardButton("پرداخت با کیف پول ✅", callback_data="pay")])
    keyboard.append([InlineKeyboardButton("استفاده از کد تخفیف 🌟", callback_data="discount")])
    keyboard.append([InlineKeyboardButton("انصراف ❌", callback_data="home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if data > 100:
        data = "نامحدود"
    text = f"-----------تایید نهایی🐈‍⬛----------\n\n" \
           f"📍نوع عملیات: {mode_text}\n" \
           f"✒️نام انتخابی: {name}\n" \
           f"📦حجم بسته: {data} GB\n" \
           f"⌛محدودیت زمانی: {expiry} روز\n" \
           f"🎁تخفیف: {discount} درصد\n" \
           f"💵قیمت: {price} تومان\n\n"
    if context.user_data['role'] == SELLER:
        text += f"💰سود شما: {price * context.user_data['multiplier']}"
    await query.edit_message_text(text, reply_markup=reply_markup)


async def request_config(context: ContextTypes.DEFAULT_TYPE):
    await load_user_data(context)
    final = context.user_data['final']
    mode = final.get("mode")
    name = final.get("name")
    price = final.get("price")
    data = final.get("data")
    expiry = final.get("expiry")
    discount = final.get("discount")

    if not context.user_data['id'] == admin_id:
        if context.user_data['balance'] < price:
            return "لطفا ابتدا حساب خود را شارژ کنید❕"
    if mode == RENEW:
        result = await api.edit_user(name, expiry, data)
    else:
        result = await api.create_user(name, expiry, data)
    if result is not None:
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        if not (context.user_data['id'] == admin_id and mode == RENEW):
            c.execute(
                """INSERT OR REPLACE INTO configs (cf_name, cf_status, cr_id, cr_name)
                            VALUES (?,?,?,?);""",
                (
                    name,
                    mode,
                    context.user_data["id"],
                    context.user_data["name"],
                ),
            )
        mode_text = "NEW"
        if mode == RENEW:
            mode_text = "RENEW"
        elif mode == GIFT:
            mode_text = "GIFT"
        elif mode == LIMITED:
            mode_text = "LIMITED"
        c.execute(
            """INSERT INTO logs (mode, name, data, price, cr_id, cr_name, time)
                        VALUES (?,?,?,?,?,?,?);""",
            (
                mode_text,
                name,
                data,
                price,
                context.user_data["id"],
                context.user_data["name"],
                datetime.date.today()
            ))
        conn.commit()
        conn.close()
        if (not mode == GIFT and not mode == LIMITED) and not context.user_data['id'] == admin_id:
            if context.user_data['role'] == CUSTOMER:
                if not context.user_data['invite'] == 0 and discount == 0:
                    multiplier = (await get_user_info(context.user_data['invite'])).get('multiplier')
                    changes = {
                        "gift": 1,
                        "profit": (multiplier * price),
                    }
                    await save_user_data(changes, context.user_data['invite'], False)
                    keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    txt = f"کاربر {context.user_data['name']} با کد معرف شما خرید {price} تومانی " \
                          f"انجام داد 🤝\n" \
                          f"سود شما از این خرید: {multiplier * price} تومان + ۱ گیگ هدیه"
                    await application.bot.send_message(chat_id=context.user_data['invite'], text=txt,
                                                       reply_markup=reply_markup)
                changes = {
                    "balance": -price,
                }
                await save_user_data(changes, context.user_data['id'], False)
            else:
                multiplier = context.user_data["multiplier"]
                changes = {
                    "balance": -price,
                    "gift": 1,
                    "profit": (multiplier * price),
                }
                await save_user_data(changes, context.user_data['id'], False)
        elif mode == GIFT:
            changes = {
                "gift": -data
            }
            await save_user_data(changes, context.user_data['id'], False)
        return result
    else:
        return "مشکلی در ساخت کانفیگ رخ داد❕"


# endregion


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await new_user(update, context)
    joined = await check_user_in_the_group(update, context)
    if joined and not (update.effective_user.id in banned_users):
        status = await get_status(context)
        keyboard = [
            [
                InlineKeyboardButton("خرید 🛒", callback_data="new"),
                InlineKeyboardButton("مدیریت سرویس ها 📦", callback_data="manage"),
            ],
            [
                InlineKeyboardButton("شارژ حساب 💰", callback_data="charge"),
            ],
            [
                InlineKeyboardButton("پنل فروش 👤", callback_data="panel"),
                InlineKeyboardButton("پشتیبانی 📨", url=f'https://t.me/{support}'),
            ],
            [
                InlineKeyboardButton("آموزش ❓", callback_data="help"),
                InlineKeyboardButton("کد معرف 🗣", callback_data="ّinvite"),
            ],
        ]
    else:
        status = "لطفا اول تو کانال پشتیبانی عضو شید 🐈‍⬛"
        keyboard = [
            [InlineKeyboardButton("ورود به کانال 🎉", url=f"https://t.me/{channel}")],
            [InlineKeyboardButton("عضو شدم ✅", callback_data="home")]
        ]

    if "access" in context.user_data and admin_started:
        await remove_handlers(context)
        if update.callback_query:
            try:
                await update.callback_query.delete_message()
            except:
                pass
        reply_markup = InlineKeyboardMarkup(keyboard)
        await application.bot.send_message(chat_id=context.user_data['id'], text=status,
                                           reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data == "home":
        await start(update, context)

    if admin_started:
        if "access" not in context.user_data:
            keyboard = [[InlineKeyboardButton("شروع مجدد 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("عملیات منقضی شده❕", reply_markup=reply_markup)
            return
        else:
            await new_user(update, context)
            await load_user_data(context)
    else:
        return

    if query.data == 'new':
        await choose_server(context, query)

    if query.data == "panel":
        if context.user_data['role'] == SELLER:
            keyboard = [
                [InlineKeyboardButton("برداشت سود 💵", url=f'https://t.me/{support}'),
                 InlineKeyboardButton("دریافت هدیه 🎁", callback_data="gift")],
                [InlineKeyboardButton("انتقال سود به موجودی 📥", callback_data="transfer")],
                [InlineKeyboardButton("بازگشت 🔄", callback_data="home")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(await get_status(context), reply_markup=reply_markup)
        else:
            await query.answer("برای دسترسی ب پنل فروش به پشتیبانی پیام دهید❕", show_alert=True)

    if query.data == 'transfer':
        await remove_handlers(context)
        keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(f'مقدار مورد نظر را بنویسید | کل سود شما: {context.user_data["profit"]}',
                                      reply_markup=reply_markup)
        context.user_data['query'] = query
        context.user_data['state'] = 'transfer'

    if query.data == 'gift':
        if context.user_data['gift'] > 0:
            await remove_handlers(context)
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(f'مقدار مورد نظر را بنویسید | کل هدیه شما: {context.user_data["gift"]}',
                                          reply_markup=reply_markup)
            context.user_data['query'] = query
            context.user_data['state'] = 'gift'
        else:
            await query.answer("شما حجم هدیه ندارید❕", show_alert=True)

    # region create config

    if query.data == 'buy':
        if active:
            await remove_handlers(context)
            context.user_data['query'] = query
            await buy(context, query)
        else:
            await query.answer("امکان خرید برای شما در حال حاضر وجود ندارد❕", show_alert=True)

    if query.data.startswith('expiry='):
        if 'config' in context.user_data:
            context.user_data['config']['expiry'] = query.data.split('=')[1]
            await buy(context, query)

    if query.data.startswith('data='):
        if 'config' in context.user_data:
            data = int(query.data.split('=')[1])
            context.user_data['config']['data'] = data
            await buy(context, query)

    if query.data.startswith('price='):
        if 'config' in context.user_data:
            price = int(query.data.split('=')[1])
            context.user_data['config']['price'] = price
            await buy(context, query)

    if query.data == 'test':
        if 'config' in context.user_data:
            context.user_data['config']['mode'] = LIMITED
            await buy(context, query)

    if query.data.startswith('name='):
        if 'config' in context.user_data:
            context.user_data['config']['name'] = query.data.split('=')[1]
            await buy(context, query)

    if query.data.startswith('back/'):
        what = query.data.split('/')[1]
        del context.user_data['config'][what]
        await buy(context, query)

    if query.data == "pay":
        await query.edit_message_text("⏳")
        final = context.user_data['final']
        mode = final.get('mode')
        if mode == LIMITED and context.user_data['limited'] >= 3:
            await query.answer("کانفیگ های تست شما تمام شده ابتدا قبلی ها را حذف یا فعال کنید❕", show_alert=True)
        else:
            config_name = final.get('name')
            result = await request_config(context)
            if result.startswith("http"):
                if mode == RENEW:
                    keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text("تمدید با موفقیت انجام شد ✅", reply_markup=reply_markup)
                else:
                    keyboard = []
                    row = []
                    for idx, loc in enumerate(settings['server']['locations']):
                        row.append(InlineKeyboardButton(text=loc, callback_data=f"links/{idx}/{config_name}"))
                    keyboard.append(row)
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    text = f"سرویس {config_name}🟢\n\n" \
                           f"لوکیشن های موجود: {' '.join(settings['server']['locations'])}\n\n" \
                           f"🔗 ساب لینک مخصوص شما \(با لمس کردن کپی کنید\):\n" \
                           f"`{result}`\n\n" \
                           f"[📱 نحوه اتصال اندروید]({settings['help']['android']})\n\n" \
                           f"[🍏 نحوه اتصال آیفون]({settings['help']['iphone']})\n\n" \
                           f"[💻 نحوه اتصال ویندوز]({settings['help']['windows']})\n\n" \
                           f"برای دریافت لینک های مربوط به هر لوکیشن بطور جداگانه از منوی پایین انتخاب کنید\."
                    await query.message.reply_text(text=text,
                                                   parse_mode=constants.ParseMode.MARKDOWN_V2,
                                                   reply_markup=reply_markup)
                    await query.edit_message_text("با موفقیت انجام شد")
                    keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.reply_text("از تنظیم بودن ساعت دستگاهتون روی اتومات اطمینان حاصل کنید❕",
                                                   reply_markup=reply_markup)
            else:
                keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(result, reply_markup=reply_markup)

    # endregion

    if query.data == "ّinvite":
        if context.user_data['role'] == CUSTOMER:
            await remove_handlers(context)
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(f'کد معرف خود را بفرستید 🗣', reply_markup=reply_markup)
            context.user_data['query'] = query
            context.user_data['state'] = 'invite'
        else:
            await query.answer("فقط برای مشتریان❕", show_alert=True)

    if query.data == "help":
        keyboard = [
            [InlineKeyboardButton("نحوه اتصال اندروید",
                                  url=settings['help']['android'])],
            [InlineKeyboardButton("نحوه اتصال آيفون",
                                  url=settings['help']['iphone'])],
            [InlineKeyboardButton("نحوه اتصال ویندوز",
                                  url=settings['help']['windows'])],
            [InlineKeyboardButton("بازگشت", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="بخش آموزش ها و لینک ها ❓\n"
                                           "درصورت وجود هر مشکل یا سوالی از پشتیبانی کمک بگیرید.",
                                      reply_markup=reply_markup)

    if query.data == "charge":
        await remove_handlers(context)
        keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"""مبلغ موردنظر را به شماره کارت
{settings['cardNumber']} - {settings['cardName']}
واریز کنید و رسید متنی یا تصویری خود را در پیام بعدی ارسال کنید:"""
        await query.edit_message_text(text, reply_markup=reply_markup)
        context.user_data['query'] = query
        context.user_data['state'] = 'receipt'

    if query.data == "discount":
        if not context.user_data['role'] == SELLER:
            backup = context.user_data['config']
            await remove_handlers(context)
            context.user_data['config'] = backup
            keyboard = [[InlineKeyboardButton("ادامه خرید 🛒", callback_data="back2buy")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = "🌟 کد تخفیف مربوط به این سرویس را بفرستید"
            await query.edit_message_text(text, reply_markup=reply_markup)
            context.user_data['query'] = query
            context.user_data['state'] = 'discount'
        else:
            await query.answer("فقط برای مشتریان❕", show_alert=True)

    if query.data == "manage":
        await query.edit_message_text("⏳")
        keyboard = []
        configs = await list_configs(context.user_data['id'])
        if configs:
            rows = []
            for config in configs:
                cf_name = config[0]
                row = InlineKeyboardButton(cf_name, callback_data=f"manage/{cf_name}")
                rows.append(row)
                if len(rows) == 2:
                    keyboard.append(rows)
                    rows = []
            if len(rows) > 0:
                keyboard.append(rows)
        keyboard.append([InlineKeyboardButton("بازگشت 🔄", callback_data="home")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.edit_message_text(
                text="کانفیگ مورد نظر را انتخاب کنید: ", reply_markup=reply_markup
            )
        except:
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="کانفیگ ها بیش از تعداد قابل نمایش❕", reply_markup=reply_markup
            )

    if query.data.startswith("manage/"):
        await query.message.edit_text("⏳")
        data = query.data.split("/")
        cf_name = data[1]
        status = await get_config_status(cf_name)
        if status is not None:
            if not cf_name.startswith("gift"):
                keyboard = [
                    [InlineKeyboardButton("تمدید سرویس 🔃", callback_data=f"renew/{cf_name}"),
                     InlineKeyboardButton("🗑️ حذف کانفیگ 🗑️", callback_data=f"remove/{cf_name}")],
                    [InlineKeyboardButton("🔗 دریافت کانفیگ 🔗", callback_data=f"get/{cf_name}")],
                    [InlineKeyboardButton("♻️ لغو مالکیت ♻️", callback_data=f"unbind/{cf_name}")],
                    [InlineKeyboardButton("بازگشت 🔄", callback_data="home")],
                ]
            else:
                keyboard = [
                    [InlineKeyboardButton("🔗 دریافت کانفیگ 🔗", callback_data=f"get/{cf_name}"),
                     InlineKeyboardButton("🗑️ حذف کانفیگ 🗑️", callback_data=f"remove/{cf_name}")],
                    [InlineKeyboardButton("بازگشت 🔄", callback_data="home")],
                ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=status, reply_markup=reply_markup)
        else:
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="کانفیگ موردنظر یافت نشد❕", reply_markup=reply_markup)

    if query.data.startswith("unbind/"):
        data = query.data.split("/")
        cf_name = data[1]
        keyboard = [
            [InlineKeyboardButton("مطمئنم❕", callback_data=f"uunbind/{cf_name}")],
            [InlineKeyboardButton("بازگشت 🔄", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("از لغو مالکیت کانفیگ مطمئن هستید؟", reply_markup=reply_markup)

    if query.data.startswith("uunbind/"):
        data = query.data.split("/")
        cf_name = data[1]
        keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(await unbind(cf_name), reply_markup=reply_markup)

    if query.data.startswith("remove/"):
        data = query.data.split("/")
        cf_name = data[1]
        info = await api.get_user(cf_name)
        usage = float(info.get("used_traffic"))
        enable = info.get("status")
        if (usage <= 0.5 or not enable) or context.user_data['id'] == admin_id:
            keyboard = [
                [InlineKeyboardButton("مطمئنم❕", callback_data=f"rremove/{cf_name}")],
                [InlineKeyboardButton("بازگشت 🔄", callback_data="home")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"از حذف کانفیگ {cf_name} مطمئن هستید؟", reply_markup=reply_markup)
        else:
            await query.answer("کانفیگ قابل حذف باید کمتر از 500 مگ استفاده کرده باشد❕", show_alert=True)

    if query.data.startswith("rremove/"):
        data = query.data.split("/")
        cf_name = data[1]
        if await api.delete_user(cf_name):
            conn = sqlite3.connect(db_address)
            c = conn.cursor()
            c.execute(f"DELETE FROM 'configs' WHERE cf_name = '{cf_name}'")
            c.execute(
                """INSERT INTO logs (mode, name, data, price, cr_id, cr_name, time)
                            VALUES (?,?,?,?,?,?,?);""",
                (
                    "REMOVE",
                    cf_name,
                    0,
                    0,
                    context.user_data["id"],
                    context.user_data["name"],
                    datetime.date.today()
                ))
            conn.commit()
            conn.close()
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"کانفیگ {cf_name} با موفقیت حذف شد!", reply_markup=reply_markup)
        else:
            await query.answer("عملیات شکست خورد❕", show_alert=True)

    if query.data.startswith("renew/"):
        context.user_data['query'] = query
        data = query.data.split('/')
        cf_name = data[1]
        config = {
            "mode": RENEW,
            "name": cf_name,
        }
        context.user_data['config'] = config
        await buy(context, query)

    if query.data.startswith("get/"):
        data = query.data.split('/')
        cf_name = data[1]
        config = (await api.get_user(cf_name)).get('subscription_url')
        keyboard = []
        row = []
        for idx, loc in enumerate(settings['server']['locations']):
            row.append(InlineKeyboardButton(text=loc, callback_data=f"links/{idx}/{cf_name}"))
        keyboard.append(row)
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"سرویس {cf_name}💎\n\n" \
               f"لوکیشن های موجود: {' '.join(settings['server']['locations'])}\n\n" \
               f"🔗 ساب لینک مخصوص شما \(با لمس کردن کپی کنید\):\n" \
               f"`{config}`\n\n" \
               f"[📱 نحوه اتصال اندروید]({settings['help']['android']})\n\n" \
               f"[🍏 نحوه اتصال آیفون]({settings['help']['iphone']})\n\n" \
               f"[💻 نحوه اتصال ویندوز]({settings['help']['windows']})\n\n" \
               f"برای دریافت لینک های مربوط به هر لوکیشن بطور جداگانه از منوی پایین انتخاب کنید\."
        await query.edit_message_text(text=text,
                                      parse_mode=constants.ParseMode.MARKDOWN_V2,
                                      reply_markup=reply_markup)
        keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("با موفقیت انجام شد", reply_markup=reply_markup)

    if query.data.startswith("bind/"):
        data = query.data.split('/')
        cf_name = data[1]
        respond = await bind(cf_name, context.user_data['id'])
        await query.answer(respond, show_alert=True)

    if query.data.startswith("links/"):
        data = query.data.split('/')
        loc = int(data[1])
        cf_name = data[2]
        location = settings['server']['locations'][loc]
        links = (await api.get_user(cf_name)).get('links')
        loc_links = await api.read_loc(links, loc)
        result = f"💎 {cf_name} \({location}\):\n\n"
        for link in loc_links:
            result += f"`{link}`\n"
        img = qrcode.make(str(loc_links[0]))
        with open(f'qr.png', 'wb') as f:
            img.save(f)
        await application.bot.send_photo(chat_id=context.user_data['id'], photo=f'qr.png',
                                         caption=result,
                                         parse_mode=constants.ParseMode.MARKDOWN_V2,
                                         reply_to_message_id=query.message.id)
        await query.answer()


# region Handlers


# region MSG_Handler

async def gift_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    amount = update.message.text
    if amount.isnumeric():
        amount = int(amount)
        if context.user_data['gift'] >= amount and not amount == 0:
            del context.user_data['state']
            context.user_data['config'] = {"mode": GIFT, "data": amount}
            await buy(context, query)
        else:
            try:
                keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("درخواست شما بیشتر از حد مجاز است، دوباره انتخاب کنید❕",
                                              reply_markup=reply_markup)
            except:
                pass
    else:
        try:
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("ورودی اشتباه است، دوباره انتخاب کنید❕", reply_markup=reply_markup)
        except:
            pass


async def check_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    amount = update.message.text
    if amount.isnumeric():
        amount = int(amount)
        if context.user_data['profit'] >= amount and not amount == 0:
            changes = {
                'profit': -amount,
                'balance': amount
            }
            await save_user_data(changes, context.user_data['id'], False)
            del context.user_data['state']
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("انتقال با موفقیت انجام شد ✅", reply_markup=reply_markup)
        else:
            try:
                keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("درخواست شما بیشتر از حد مجاز است، دوباره انتخاب کنید❕",
                                              reply_markup=reply_markup)
            except:
                pass
    else:
        try:
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("ورودی اشتباه است، دوباره انتخاب کنید❕", reply_markup=reply_markup)
        except:
            pass


async def check_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    text1 = f"-CHARGE REQUEST-\n\n" \
            f"ID: {context.user_data['id']}\n" \
            f"Name: {context.user_data['name']}\n" \
            f"Username: @{context.user_data['username']}"
    text2 = f"`/balance {context.user_data['id']}` amount\n" \
            f"`/decline {context.user_data['id']}`"
    msg = await update.effective_message.forward(chat_id=admin_id)
    await context.bot.send_message(chat_id=admin_id, text=text1, reply_to_message_id=msg.id)
    await context.bot.send_message(chat_id=admin_id, text=text2, parse_mode=constants.ParseMode.MARKDOWN_V2)
    keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("درخواست شما انجام شد")
    await update.message.reply_text(reply_to_message_id=update.message.id,
                                    text='رسید شما در انتظار تایید ادمین قرار گرفت و نتیجه به شما اعلام می شود ⏳',
                                    reply_markup=reply_markup)


async def check_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    cr_id = update.message.text
    if cr_id.isnumeric():
        cr_id = int(cr_id)
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"SELECT role FROM 'users' WHERE id = {cr_id}")
        found = c.fetchone()
        conn.close()
        if found and found[0] == SELLER:
            if not context.user_data['invite'] == cr_id:
                del context.user_data['state']
                changes = {
                    'invite': cr_id
                }
                await save_user_data(changes, context.user_data['id'], True)
                keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await application.bot.send_message(chat_id=cr_id,
                                                   text=f"کاربر {context.user_data['name']} شما را به عنوان معرف خود انتخاب کرد 🤍")
                await query.edit_message_text(
                    f"کاربر {(await get_user_info(cr_id)).get('name')} به عنوان معرف شما انتخاب شد 🤍",
                    reply_markup=reply_markup)
            else:
                try:
                    keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text("کاربر مورد نظر معرف شماست", reply_markup=reply_markup)
                except:
                    pass
        else:
            try:
                keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("کاربر مورد نظر فروشنده نیست", reply_markup=reply_markup)
            except:
                pass
    else:
        try:
            keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("کاربر مورد نظر یافت نشد، دوباره امتحان کنید", reply_markup=reply_markup)
        except:
            pass


async def check_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    config_name = update.message.text
    pattern = r'^[a-zA-Z0-9]+$'
    if len(config_name) > 3 and re.match(pattern, config_name) is not None:
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"SELECT 1 FROM 'configs' WHERE cf_name = '{config_name}'")
        found = c.fetchone()
        conn.close()
        if not found:
            del context.user_data['state']
            context.user_data['config']['name'] = config_name
            await query.edit_message_text("⏳")
            await buy(context, query)
        else:
            try:
                keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("نام از قبل انتخاب شده", reply_markup=reply_markup)
            except:
                pass
    else:
        try:
            keyboard = [[InlineKeyboardButton("انصراف ❌", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("نام غیرقابل قبول، مجددا تلاش کنید", reply_markup=reply_markup)
        except:
            pass


async def check_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    msg = update.message.text
    await query.message.edit_text("⏳")
    data = None
    if msg.startswith("vmess") or msg.startswith("vless"):
        data = await api.find_config(msg)
    if data:
        del context.user_data['state']
        await query.message.edit_text("اطلاعات کانفیگ یافت شد")
        cf_name = data.get('username')

        if data.get("status"):
            enabled = "روشن 🟢"
        else:
            enabled = "خاموش 🔴"
        expiry = data.get("expire")
        if expiry == 0:
            expiry = "کمتر از یک"
        elif expiry < 0:
            expiry = "0"
        cf_data = data.get("data_limit")
        if round(float(cf_data)) > 100:
            cf_data = "♾️"
        text = "-وضعیت بسته-\n" \
               f"\n✒️نام بسته: {cf_name}" \
               f"\n📦حجم بسته: {cf_data} GB" \
               f"\n⬇️حجم استفاده شده: {data.get('used_traffic')} GB" \
               f"\n👥تعداد کاربر: {data.get('users')}" \
               f"\n⌛زمان مانده: {expiry} روز\n" \
               f"\nوضعیت سرویس: {enabled}"
        keyboard = []
        if not cf_name.startswith("gift"):
            keyboard.append(
                [InlineKeyboardButton("تمدید سرویس 💡", callback_data=f"renew/{cf_name}")])
            keyboard.append(
                [InlineKeyboardButton("افزودن به لیست شما 📥", callback_data=f"bind/{cf_name}")])
        keyboard.append([InlineKeyboardButton("بازگشت 🔄", callback_data="home")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(reply_to_message_id=update.message.id, text=text,
                                       reply_markup=reply_markup)
    else:
        try:
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(text="کانفیگ موردنظر درست نیست، مجددا تلاش کنید❕", reply_markup=reply_markup)
        except:
            pass


async def check_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = context.user_data['query']
    user_code = update.message.text
    keyboard = [[InlineKeyboardButton("بازگشت 🛒", callback_data="back2buy")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    found = False
    for ds in discounts:
        code = ds.get('code')
        if code == user_code:
            found = True
            context.user_data['config']['discount'] = ds.get('discount')
            await query.answer(f"کد تخفیف {ds.get('discount')} درصدی شما روی سرویس اعمال شد 💝",
                               show_alert=True)
            del context.user_data['state']
    if not found:
        try:
            await query.edit_message_text("کد تخفیف شما درست نیست! دوباره امتحان کنید❕", reply_markup=reply_markup)
        except:
            pass


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if admin_started:
        await load_user_data(context)
        if 'state' in context.user_data and 'query' in context.user_data:
            if context.user_data['state'] == 'receipt':
                await check_receipt(update, context)

            elif context.user_data['state'] == 'transfer':
                await check_transfer(update, context)

            elif context.user_data['state'] == 'name':
                await check_name(update, context)

            elif context.user_data['state'] == 'gift':
                await gift_amount(update, context)

            elif context.user_data['state'] == 'discount':
                await check_discount(update, context)

            elif context.user_data['state'] == 'invite':
                await check_invite(update, context)


# endregion


async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document.file_name == 'settings.json':
        try:
            with open("settings.json", 'rb') as file:
                await update.message.reply_document(document=file, caption="Settings " + str(datetime.date.today()))
        except:
            await update.message.reply_text("مشکلی در ارسال تنظیمات قبلی پیش آمد❕")
        file_id = update.message.document.file_id
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive('settings.json')
        await update.message.reply_text(reply_to_message_id=update.message.id,
                                        text="تنظیمات جدید نصب شد، /reset برای اعمال ✅")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'state' in context.user_data and 'query' in context.user_data:
        if context.user_data['state'] == 'receipt':
            query = context.user_data['query']
            del context.user_data['state']
            text1 = f"-CHARGE REQUEST-\n\n" \
                    f"ID: {context.user_data['id']}\n" \
                    f"Name: {context.user_data['name']}\n" \
                    f"Username: @{context.user_data['username']}"
            text2 = f"`/balance {context.user_data['id']}` amount\n" \
                    f"`/decline {context.user_data['id']}`"
            msg = await update.effective_message.forward(chat_id=admin_id)
            await context.bot.send_message(chat_id=admin_id, text=text1, reply_to_message_id=msg.id)
            await context.bot.send_message(chat_id=admin_id, text=text2, parse_mode=constants.ParseMode.MARKDOWN_V2)
            keyboard = [[InlineKeyboardButton("بازگشت 🔄", callback_data="home")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("درخواست شما انجام شد")
            await update.message.reply_text(reply_to_message_id=update.message.id,
                                            text='رسید شما در انتظار تایید ادمین قرار گرفت و نتیجه به شما اعلام می '
                                                 'شود ⏳', reply_markup=reply_markup)


# endregion


# region CALLBACKS

async def seller_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 1 and context.args[0].isnumeric():
        target_id = context.args[0]
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"SELECT role FROM 'users' WHERE id = {target_id}")
        role = c.fetchone()[0]
        if role == SELLER:
            c.execute(f"UPDATE 'users' SET role = {CUSTOMER} WHERE id = {target_id}")
            text = "دسترسی شما به مشتری تغییر کرد"
            text2 = f"دسترسی کاربر {target_id} به مشتری تغییر کرد"
        else:
            c.execute(f"UPDATE 'users' SET role = {SELLER} WHERE id = {target_id}")
            c.execute(f"UPDATE 'users' SET invite = 0 WHERE id = {target_id}")
            text = "دسترسی شما به فروشنده تغییر کرد✅"
            text2 = f"دسترسی کاربر {target_id} به فروشنده تغییر کرد✅"
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(reply_to_message_id=update.effective_message.id, text=text2)
        await application.bot.send_message(chat_id=target_id, text=text,
                                           reply_markup=reply_markup)


async def balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 2 and context.args[0].isnumeric() and context.args[1]:
        target_id = context.args[0]
        amount = int(context.args[1])
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"UPDATE 'users' SET balance = balance + {amount} WHERE id = {target_id}")
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if amount >= 0:
            msg = f"حساب شما به مقدار {amount} تومان شارژ شد✅"
            admin_msg = f"حساب کاربر {target_id} به مقدار {amount} تومان شارژ شد✅"
        else:
            msg = f"حساب شما به مقدار {amount} تومان کم شد!"
            admin_msg = f"حساب کاربر {target_id} به مقدار {amount} تومان کم شد!"
        await context.bot.send_message(chat_id=target_id, text=msg, reply_markup=reply_markup)
        await update.message.reply_text(reply_to_message_id=update.effective_message.id, text=admin_msg)


async def profit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 2 and context.args[0].isnumeric() and context.args[1]:
        target_id = context.args[0]
        amount = int(context.args[1])
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"UPDATE 'users' SET profit = profit + {amount} WHERE id = {target_id}")
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if amount >= 0:
            msg = f" {amount} تومان سود هدیه دریافت کردید 💸"
            admin_msg = f" کاربر {target_id}، {amount} تومان سود هدیه دریافت کرد 💸"
        else:
            msg = f" {amount} تومان از سود شما کم شد!"
            admin_msg = f"از کاربر {target_id}، {amount} تومان سود کم شد!"
        await context.bot.send_message(chat_id=target_id, text=msg, reply_markup=reply_markup)
        await update.message.reply_text(reply_to_message_id=update.effective_message.id, text=admin_msg)


async def decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 1 and context.args[0].isnumeric():
        target_id = context.args[0]
        keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=target_id, text="درخواست شما از طرف ادمین رد شد ❌",
                                       reply_markup=reply_markup)
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="درخواست کاربر از طرف ادمین رد شد ❌")


async def gift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 2 and context.args[0].isnumeric() and context.args[1].isnumeric():
        target_id = context.args[0]
        amount = int(context.args[1])
        conn = sqlite3.connect(db_address)
        c = conn.cursor()
        c.execute(f"UPDATE 'users' SET gift = gift + {amount} WHERE id = {target_id}")
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=target_id, text=f"شما {amount} گیگ حجم هدیه دریافت کردید 🎁",
                                       reply_markup=reply_markup)
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text=f"کاربر {amount} گیگ حجم هدیه دریافت کرد ✅")


async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if load_settings():
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="RESETED SUCCESSFULY /start")
    else:
        global admin_started
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="couldn't read settings! waiting for admin reply")
        admin_started = False


async def users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT * FROM 'users'")
    users = c.fetchall()
    results = f"- USERS & CONFIGS : {datetime.datetime.now()} -\n\n"
    for user in users:
        results += f"👤ID: {user[0]}\nName: {user[1]}\nUserName: @{user[2]}\n" \
                   f"💳Balance: {user[3]}, Profit: {user[4]}, Gift: {user[5]}\n\n"
        c.execute(f"SELECT * FROM 'configs' WHERE cr_id = {user[0]}")
        configs = c.fetchall()
        for config in configs:
            config_data = f"    📍Name: {config[0]} - Status: {config[1]}\n\n"
            results += config_data
        results += "--------------------------------\n\n"
    conn.close()
    with open("users.txt", "w", encoding="utf-8") as f:
        f.write(results)
    file = open("users.txt", "r", encoding="utf-8")
    await update.message.reply_document(file)


async def backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(api.backup_file, 'rb') as file:
            await update.message.reply_document(document=file)
    except:
        await update.message.reply_text("مشکلی در ارسال پشتیبان رخ داد")


async def sellers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT * FROM 'users' WHERE role = {SELLER}")
    users = c.fetchall()
    results = f"- SELLERS STATUS : {datetime.datetime.now()} -\n\n"
    for user in users:
        results += f"👤{user[0]}\n{user[1]} | @{user[2]}\n" \
                   f"Balance: {user[3]}, Profit: {user[4]}, Gift: {user[5]}\n\n"
    conn.close()
    await update.message.reply_text(reply_to_message_id=update.effective_message.id, text=results)


async def get_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT * FROM 'logs'")
    users = c.fetchall()
    results = f"- LOG : {datetime.datetime.now()} -\n\n"
    for user in users:
        # (mode, name, data, price, cr_id, cr_name, time)
        results += f"{user[6]}\naction: {user[0]} | 👤: {user[5]} | id: {user[4]} \n" \
                   f" config: {user[1]} | {user[2]}GB {user[3]}T \n\n"
    conn.close()
    with open("logs.txt", "w", encoding="utf-8") as f:
        f.write(results)
    await update.message.reply_document(open("logs.txt", "r", encoding="utf-8"))
    try:
        with open("users.db", 'rb') as file:
            await update.message.reply_document(document=file)
        with open("settings.json", 'rb') as file:
            await update.message.reply_document(document=file)
        with open("nohup.out", 'rb') as file:
            await update.message.reply_document(document=file)
    except:
        await update.message.reply_text("couldn't send all the log files")


async def msg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) >= 2 and context.args[0].isnumeric():
        target_id = int(context.args[0])
        msg = ''
        for word in context.args[1:]:
            msg += ' ' + word
        text = "👤 پیامی از طرف ادمین:\n" + msg
        if target_id == 0:
            conn = sqlite3.connect(db_address)
            c = conn.cursor()
            c.execute(f"SELECT id FROM 'users'")
            rows = c.fetchall()
            for row in rows:
                _id = row[0]
                try:
                    await application.bot.send_message(chat_id=_id, text=text)
                except:
                    pass
            await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                            text=f"پیام شما به کاربران ارسال شد ✅")
        else:
            await application.bot.send_message(chat_id=target_id, text=text)
            await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                            text=f"پیام شما به کاربر {target_id} ارسال شد ✅")
    else:
        await update.message.reply_text(reply_to_message_id=update.effective_message.id, text="آیدی اشتباه است.")


async def update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔃بروزرسانی وضعیت🔃", callback_data="home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    conn = sqlite3.connect(db_address)
    c = conn.cursor()
    c.execute(f"SELECT id FROM 'users'")
    rows = c.fetchall()
    for row in rows:
        _id = row[0]
        try:
            await application.bot.send_message(chat_id=_id,
                                               text="ربات بروز رسانی شد لطفا یکبار روی /start کلیک کنید 💫",
                                               reply_markup=reply_markup)
        except:
            pass
    await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                    text=f"پیام آپدیت به کاربران ارسال شد ✅")


async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = context.args[0]
    if command == "help":
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text=" - command help - \n/user {ban, unban} {id}\n/user list")
    elif len(context.args) == 2 and context.args[1].isnumeric():
        user_id = int(context.args[1])
        if command == "ban":
            if not user_id in banned_users:
                banned_users.append(user_id)
                await update.message.reply_text(f"کاربر {user_id} به لیست بن اضافه شد ⛔")
                try:
                    await application.bot.send_message(chat_id=user_id, text="اکانت شما بن شد ⛔")
                except:
                    pass
        elif command == "unban":
            if user_id in banned_users:
                banned_users.remove(user_id)
                await update.message.reply_text(f"کاربر {user_id} از لیست بن خارج شد ☑️")
                try:
                    await application.bot.send_message(chat_id=user_id, text="اکانت شما بن شد ☑️")
                except:
                    pass
    elif command == "list":
        ban_list = '👤banned users list👤\n\n'
        for ban in banned_users:
            ban_list += f"- {str(ban)} is banned \n"
        await update.message.reply_text(ban_list)
    await save_status()


async def find_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(reply_to_message_id=update.effective_message.id,text="⏳")
    target = context.args[0]
    configs = await api.find(target)
    keyboard = [[InlineKeyboardButton("بازگشت", callback_data=f"home")]]
    rows = []
    for cf_name in configs:
        row = InlineKeyboardButton(cf_name, callback_data=f"manage/{cf_name}")
        rows.append(row)
        if len(rows) == 2:
            keyboard.append(rows)
            rows = []
    if len(rows) > 0:
        keyboard.append(rows)
    reply_markup = InlineKeyboardMarkup(keyboard)
    await msg.edit_text(text="کانفیگ های یافت شده",
                        reply_markup=reply_markup)


async def discount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global discounts
    command = context.args[0]
    if command == "help":
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text=" - command help - \n/discount new {code} {discount}\n/discount clear\n/discount list")
    elif command == "list":
        msg = 'تخفیف های فعال:\n\n'
        for dc in discounts:
            msg += f"Code: {dc.get('code')} |  discount: {dc.get('code')}\n"
        await update.message.reply_text(msg)
    elif command == "new":
        code = context.args[1]
        discount = int(context.args[2])
        cp = {'code': code, 'discount': discount}
        discounts.append(cp)
        await update.message.reply_text(str(cp))
    elif command == "clear":
        discounts = []
    await save_status()


async def bind_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args[0].isnumeric():
        target = int(context.args[0])
        name = context.args[1]
        await context.application.bot.send_message(chat_id=target, text=(await bind(name, target)),
                                                   reply_to_message_id=update.effective_message.id)


async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active
    if active:
        active = False
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="خرید برای کاربران بسته شد.")
    else:
        active = True
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="خرید برای کاربران باز شد.")


async def testing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global testing
    if testing:
        testing = False
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="تست برای کاربران بسته شد.")
    else:
        testing = True
        await update.message.reply_text(reply_to_message_id=update.effective_message.id,
                                        text="تست برای کاربران باز شد.")


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = "💬Basic Commands\n\n" \
             "/msg {id} {text}\nsend message to specific user ( use 0 as id for send to all )\n" \
             "/balance {id} {amount}\nincrease or decrease balance from user\n" \
             "/decline {id}\nsend decline message to user\n" \
             "/profit {id} {amount}\nincrease or decrease profit from seller\n" \
             "/discount {action}\nactions: ['help', 'new', 'clear', 'list'] \n" \
             "/user {action}\nactions: ['help', 'new', 'clear', 'list'] \n" \
             "/srv {action}\nactions: ['help', 'close', 'open', 'list', 'test'] \n\n" \
             "👤Sellers Management Commands\n\n" \
             "/seller {id}\nswitch user role\n" \
             "/sellers\nshow sellers status\n" \
             "/gift {id} {amount}\nincrease or decrease gift data from seller\n" \
             "/profit {id} {amount}\nincrease or decrease profit from seller\n\n" \
             "⚙️Advanced Commands\n\n" \
             "/find {key-word}\nsearch for key-word in configs across all servers\n" \
             "/update\nsend update message to all users\n" \
             "/users\nsend users data as readable file\n" \
             "/logs\nsend logs, settings and errors as files\n" \
             "/reset\nre-login to servers and re-read settings\n" \
             "/cleanup\nclean-up servers and remove every disabled configs (older than 7 days)\n\n" \
             "sending settings.json at any moment will replace the old settings.json"
    await update.message.reply_text(reply_to_message_id=update.effective_message.id, text=result)


# endregion


def main() -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.ATTACHMENT, file_handler))
    application.add_handler(CommandHandler("seller", seller_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("sellers", sellers_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("balance", balance_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("decline", decline_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("profit", profit_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("gift", gift_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("update", update_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("users", users_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("logs", get_log, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("msg", msg_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("reset", reset_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("find", find_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("user", user_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("discount", discount_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("help", help_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("active", active_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("testing", testing_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("backup", backup_callback, filters.Chat(admin_id)))
    application.add_handler(CommandHandler("bind", bind_callback, filters.Chat(admin_id)))
    application.run_polling()


if __name__ == "__main__":
    main()
