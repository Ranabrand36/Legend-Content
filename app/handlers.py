import asyncio
import logging
from datetime import datetime
from html import escape
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from config import OWNER_ID, WELCOME_TEXT, SUPPORT_USERNAME, BOT_PUBLIC_URL
from app import db
from app.states import (AddContent, AddChannel, AddPaymentMethod, SubmitPayment, Broadcast,
                         EditContentPrice, SetBotSetting, EditContentInfo)
from app.keyboards import (
    user_menu, admin_menu, back_admin, join_keyboard, content_keyboard,
    payment_method_keyboard, payment_review_keyboard
)

router = Router()
log = logging.getLogger(__name__)

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

async def require_owner(message: Message) -> bool:
    if not message.from_user or not is_owner(message.from_user.id):
        await message.answer("⛔ You are not authorized.")
        return False
    return True

async def check_join(bot: Bot, user_id: int):
    enabled = await db.get_setting("force_join_enabled", "1")
    if enabled != "1":
        return []
    channels = await db.get_channels()
    if not channels:
        return []

    # Check required channels concurrently instead of waiting for each Telegram
    # API request sequentially. Limit concurrency to avoid flooding Telegram.
    semaphore = asyncio.Semaphore(5)

    async def check_one(ch):
        async with semaphore:
            try:
                member = await bot.get_chat_member(ch["chat_id"], user_id)
                status = getattr(member, "status", "")
                is_member = status in ("creator", "administrator", "member")
                if status == "restricted":
                    is_member = bool(getattr(member, "is_member", False))
                return None if is_member else ch
            except Exception as exc:
                log.warning("Force-join check failed for %s: %s", ch["chat_id"], exc)
                return ch

    results = await asyncio.gather(*(check_one(ch) for ch in channels))
    return [ch for ch in results if ch is not None]

async def send_join_gate(target, channels, code=""):
    text = "🔒 <b>Access Required</b>\n\nPlease join all required channels, then tap Verify."
    await target.answer(text, reply_markup=join_keyboard(channels, code))

async def deliver_content(bot: Bot, chat_id: int, content):
    protect = bool(content["protect"])
    desc = content["description"] or ""
    title = f"📦 <b>{escape(content['title'])}</b>"
    safe_desc = escape(desc)
    caption = (title + ("\n\n" + safe_desc if safe_desc else ""))[:1000]
    typ = content["content_type"]
    file_id = content["file_id"]
    body = content["body"] or ""
    if typ == "text":
        await bot.send_message(chat_id, f"{title}\n\n{escape(body)}", protect_content=protect)
    elif typ == "link":
        await bot.send_message(chat_id, f"{title}\n\n{safe_desc}\n{escape(body)}", protect_content=protect, disable_web_page_preview=True)
    elif typ == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption, protect_content=protect)
    elif typ == "video":
        await bot.send_video(chat_id, file_id, caption=caption, protect_content=protect)
    elif typ == "audio":
        await bot.send_audio(chat_id, file_id, caption=caption, protect_content=protect)
    elif typ == "voice":
        await bot.send_voice(chat_id, file_id, caption=caption, protect_content=protect)
    elif typ == "animation":
        await bot.send_animation(chat_id, file_id, caption=caption, protect_content=protect)
    elif typ == "video_note":
        await bot.send_video_note(chat_id, file_id, protect_content=protect)
        if desc:
            await bot.send_message(chat_id, desc, protect_content=protect)
    else:
        await bot.send_document(chat_id, file_id, caption=caption, protect_content=protect)

async def content_page(message_or_call, bot: Bot, user_id: int, content_id: int):
    content = await db.get_content(content_id)
    if not content or not content["active"]:
        text = "This content is unavailable."
        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.answer(text, show_alert=True)
        else:
            await message_or_call.answer(text)
        return
    missing = await check_join(bot, user_id)
    if missing:
        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.message.answer(
                "🔒 Join required channels first.", reply_markup=join_keyboard(missing, content["code"]))
        else:
            await send_join_gate(message_or_call, missing, content["code"])
        return
    if content["is_free"] or await db.has_purchase(user_id, content_id):
        await deliver_content(bot, user_id, content)
        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.answer("Content delivered.")
        return
    text = (f"💎 <b>{escape(content['title'])}</b>\n\n{escape(content['description'] or '')}\n\n"
            f"Price: <b>PKR {content['price']:,.0f}</b>\n\nSelect a payment method to request access.")
    methods = await db.get_payment_methods()
    if not methods:
        text += "\n\n⚠️ No payment method is configured yet. Please contact the admin."
        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.message.answer(text)
            await message_or_call.answer()
        else:
            await message_or_call.answer(text)
        return
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=payment_method_keyboard(methods, content_id))
        await message_or_call.answer()
    else:
        await message_or_call.answer(text, reply_markup=payment_method_keyboard(methods, content_id))

def media_details(message: Message):
    if message.photo:
        return "photo", message.photo[-1].file_id, None
    if message.video:
        return "video", message.video.file_id, None
    if message.document:
        return "document", message.document.file_id, None
    if message.audio:
        return "audio", message.audio.file_id, None
    if message.voice:
        return "voice", message.voice.file_id, None
    if message.animation:
        return "animation", message.animation.file_id, None
    if message.video_note:
        return "video_note", message.video_note.file_id, None
    if message.text:
        text = message.text.strip()
        if text.startswith(("https://", "http://", "tg://")):
            return "link", None, text
        return "text", None, text
    return None, None, None

@router.message(Command("cancel"))
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Current action cancelled.", reply_markup=admin_menu() if is_owner(message.from_user.id) else user_menu())

@router.message(CommandStart())
async def start(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    await db.save_user(user.id, user.username, user.first_name)
    payload = ""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        payload = parts[1].strip()
    if payload.startswith("c_"):
        code = payload[2:]
        missing = await check_join(bot, user.id)
        if missing:
            await send_join_gate(message, missing, code)
            return
        content = await db.get_content_by_code(code)
        if not content:
            await message.answer("This content link is invalid or unavailable.", reply_markup=user_menu())
            return
        await content_page(message, bot, user.id, content["id"])
        return
    missing = await check_join(bot, user.id)
    if missing:
        await send_join_gate(message, missing)
        return
    welcome = await db.get_setting("welcome_text", WELCOME_TEXT)
    await message.answer(welcome, reply_markup=user_menu())

@router.callback_query(F.data.startswith("verify:"))
async def verify_join(call: CallbackQuery, bot: Bot):
    code = call.data.split(":", 1)[1]
    missing = await check_join(bot, call.from_user.id)
    if missing:
        await call.answer("You have not joined all required channels yet.", show_alert=True)
        await call.message.answer("Please join the remaining channels:", reply_markup=join_keyboard(missing, code))
        return
    await call.answer("Membership verified!")
    if code not in ("", "home"):
        content = await db.get_content_by_code(code)
        if content:
            # Use the chat message here because the callback was already answered above.
            await content_page(call.message, bot, call.from_user.id, content["id"])
            return
    await call.message.answer("✅ Membership verified. Welcome!", reply_markup=user_menu())

@router.callback_query(F.data == "user:home")
async def user_home(call: CallbackQuery, bot: Bot):
    missing = await check_join(bot, call.from_user.id)
    if missing:
        await call.message.answer("Join required channels:", reply_markup=join_keyboard(missing))
    else:
        await call.message.answer("👑 <b>Legend Content Hub</b>", reply_markup=user_menu())
    await call.answer()

@router.callback_query(F.data.in_({"user:browse", "user:free", "user:paid"}))
async def browse(call: CallbackQuery, bot: Bot):
    missing = await check_join(bot, call.from_user.id)
    if missing:
        await call.message.answer("Join required channels:", reply_markup=join_keyboard(missing))
        await call.answer()
        return
    mode = call.data.split(":")[1]
    rows = await db.list_contents(limit=30)
    if mode == "free":
        rows = [r for r in rows if r["is_free"]]
    elif mode == "paid":
        rows = [r for r in rows if not r["is_free"]]
    if not rows:
        await call.message.answer("No content available in this section.")
    else:
        buttons = []
        for c in rows:
            label = f"{'🆓' if c['is_free'] else '💎'} {c['title'][:42]}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"content:{c['id']}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="user:home")])
        await call.message.answer("📦 <b>Available Content</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@router.callback_query(F.data.startswith("content:"))
async def content_callback(call: CallbackQuery, bot: Bot):
    cid = int(call.data.split(":")[1])
    await content_page(call, bot, call.from_user.id, cid)

@router.callback_query(F.data == "user:purchases")
async def purchases(call: CallbackQuery, bot: Bot):
    missing = await check_join(bot, call.from_user.id)
    if missing:
        await call.message.answer("Join required channels:", reply_markup=join_keyboard(missing))
        await call.answer()
        return
    rows = await db.fetchall("""
        SELECT c.* FROM purchases p JOIN contents c ON c.id=p.content_id
        WHERE p.user_id=? ORDER BY p.purchased_at DESC LIMIT 30
    """, (call.from_user.id,))
    if not rows:
        await call.message.answer("You have no approved purchases yet.")
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📦 {c['title'][:45]}", callback_data=f"content:{c['id']}")]
            for c in rows
        ])
        await call.message.answer("🛒 <b>Your Purchases</b>", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data == "user:account")
async def account(call: CallbackQuery):
    user = await db.fetchone("SELECT * FROM users WHERE telegram_id=?", (call.from_user.id,))
    await call.message.answer(
        f"👤 <b>Your Account</b>\nID: <code>{call.from_user.id}</code>\n"
        f"Name: {escape(call.from_user.first_name)}\nUsername: @{escape(call.from_user.username or 'not set')}\n"
        f"Joined: {user['joined_at'] if user else 'Unknown'}")
    await call.answer()

@router.callback_query(F.data == "user:support")
async def support(call: CallbackQuery):
    username = (await db.get_setting("support_username", SUPPORT_USERNAME)).lstrip("@")
    if username:
        await call.message.answer(f"📞 Support: @{username}")
    else:
        await call.message.answer("Please contact the bot owner for support.")
    await call.answer()

@router.callback_query(F.data.startswith("link:"))
async def make_link(call: CallbackQuery, bot: Bot):
    cid = int(call.data.split(":")[1])
    content = await db.get_content(cid)
    if not content:
        await call.answer("Content not found.", show_alert=True)
        return
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=c_{content['code']}"
    await call.message.answer(f"🔗 <b>Unique content link</b>\n<a href=\"{link}\">Open content</a>\n<code>{link}</code>")
    await call.answer()

# -------------------- OWNER PANEL --------------------

@router.message(Command("admin"))
async def admin_command(message: Message):
    if not await require_owner(message):
        return
    stats = await db.get_stats()
    await message.answer(
        f"👑 <b>LEGEND CONTENT HUB — OWNER PANEL</b>\n\n"
        f"👥 Users: {stats['users']}\n📁 Content: {stats['contents']}\n"
        f"⏳ Pending payments: {stats['pending']}\n✅ Approved payments: {stats['approved']}",
        reply_markup=admin_menu())

@router.callback_query(F.data == "admin:home")
async def admin_home(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    await call.message.answer("👑 <b>Owner Panel</b>", reply_markup=admin_menu())
    await call.answer()

@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    s = await db.get_stats()
    await call.message.answer(
        "📊 <b>Dashboard</b>\n\n"
        f"👥 Active users: {s['users']}\n📁 Active content: {s['contents']}\n"
        f"⏳ Pending payments: {s['pending']}\n✅ Approved payments: {s['approved']}\n"
        f"🛒 Purchases: {s['purchases']}", reply_markup=back_admin())
    await call.answer()

@router.callback_query(F.data == "admin:add")
async def add_content_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AddContent.title)
    await call.message.answer("📁 Send the content title:")
    await call.answer()

@router.message(AddContent.title)
async def add_content_title(message: Message, state: FSMContext):
    if not await require_owner(message): return
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer("Title must be 1–100 characters. Try again.")
        return
    await state.update_data(title=title)
    await state.set_state(AddContent.description)
    await message.answer("Send a short description (or send - for no description):")

@router.message(AddContent.description)
async def add_content_description(message: Message, state: FSMContext):
    if not await require_owner(message): return
    await state.update_data(description="" if (message.text or "").strip() == "-" else (message.text or "")[:500])
    await state.set_state(AddContent.price)
    await message.answer("Send price in PKR (e.g. 250) or type <code>free</code>:")

@router.message(AddContent.price)
async def add_content_price(message: Message, state: FSMContext):
    if not await require_owner(message): return
    data = await state.get_data()
    value = (message.text or "").strip().lower()
    if value == "free":
        price = 0
    else:
        try:
            price = float(value)
            if price <= 0 or price > 100000000:
                raise ValueError
        except ValueError:
            await message.answer("Enter a valid positive PKR amount or type free.")
            return
    if "edit_content_id" in data:
        await db.update_content_price(data["edit_content_id"], price)
        await state.clear()
        await message.answer("✅ Content price updated.", reply_markup=admin_menu())
        return
    await state.update_data(price=price)
    await state.set_state(AddContent.payload)
    await message.answer("Now send the actual content: text, link, photo, video, audio, voice, animation or document.")

@router.message(AddContent.payload)
async def add_content_payload(message: Message, state: FSMContext):
    if not await require_owner(message): return
    typ, file_id, body = media_details(message)
    if not typ:
        await message.answer("Unsupported message. Send text, link, photo, video, audio or a document.")
        return
    data = await state.get_data()
    row = await db.create_content(data["title"], data["description"], typ, file_id, body, data["price"])
    await state.clear()
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=c_{row['code']}"
    await message.answer(
        f"✅ <b>Content added successfully!</b>\n\nID: <code>{row['id']}</code>\n"
        f"Code: <code>{row['code']}</code>\nType: {typ}\nPrice: "
        f"{'FREE' if row['is_free'] else f'PKR {row['price']:,.0f}'}\n\n"
        f"Share link: <a href=\"{link}\">Open content</a>\n<code>{link}</code>", reply_markup=admin_menu())

@router.callback_query(F.data == "admin:contents")
async def manage_contents(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    rows = await db.list_contents(active_only=False, limit=25)
    if not rows:
        await call.message.answer("No content uploaded yet.", reply_markup=back_admin())
    else:
        buttons = []
        for c in rows:
            status = "🟢" if c["active"] else "⚫"
            price = "FREE" if c["is_free"] else f"PKR {c['price']:g}"
            buttons.append([InlineKeyboardButton(text=f"{status} #{c['id']} {c['title'][:28]} · {price}",
                                                callback_data=f"managecontent:{c['id']}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
        await call.message.answer("🗂 <b>Manage Content</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@router.callback_query(F.data.startswith("managecontent:"))
async def manage_one_content(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    c = await db.get_content(cid)
    if not c:
        await call.answer("Not found.", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢/⚫ Toggle Active", callback_data=f"contenttoggle:{cid}")],
        [InlineKeyboardButton(text="✏️ Edit Title / Description", callback_data=f"contentedit:{cid}")],
        [InlineKeyboardButton(text="💰 Change Price", callback_data=f"contentprice:{cid}")],
        [InlineKeyboardButton(text="🔗 Get Link", callback_data=f"link:{cid}")],
        [InlineKeyboardButton(text="🗑 Delete", callback_data=f"contentdelete:{cid}")],
        [InlineKeyboardButton(text="⬅️ Content List", callback_data="admin:contents")]
    ])
    await call.message.answer(
        f"<b>{c['title']}</b>\nID: {cid}\nType: {c['content_type']}\n"
        f"Price: {'FREE' if c['is_free'] else f'PKR {c['price']:,.0f}'}\n"
        f"Active: {bool(c['active'])}", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("contenttoggle:"))
async def content_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    await db.toggle_content(cid)
    c = await db.get_content(cid)
    await call.answer("Content status updated.")
    if c:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢/⚫ Toggle Active", callback_data=f"contenttoggle:{cid}")],
            [InlineKeyboardButton(text="✏️ Edit Title / Description", callback_data=f"contentedit:{cid}")],
            [InlineKeyboardButton(text="💰 Change Price", callback_data=f"contentprice:{cid}")],
            [InlineKeyboardButton(text="🔗 Get Link", callback_data=f"link:{cid}")],
            [InlineKeyboardButton(text="🗑 Delete", callback_data=f"contentdelete:{cid}")],
            [InlineKeyboardButton(text="⬅️ Content List", callback_data="admin:contents")]
        ])
        await call.message.answer(
            f"<b>{c['title']}</b>\nID: {cid}\nType: {c['content_type']}\n"
            f"Price: {'FREE' if c['is_free'] else f'PKR {c['price']:,.0f}'}\n"
            f"Active: {bool(c['active'])}", reply_markup=kb)

@router.callback_query(F.data.startswith("contentdelete:"))
async def content_delete_confirm(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Confirm Delete", callback_data=f"contentdeleteyes:{cid}"),
        InlineKeyboardButton(text="Cancel", callback_data=f"managecontent:{cid}")
    ]])
    await call.message.answer("Delete this content and its linked payment/purchase records?", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("contentdeleteyes:"))
async def content_delete(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    await db.delete_content(cid)
    await call.message.answer("🗑 Content deleted.", reply_markup=back_admin())
    await call.answer()

@router.callback_query(F.data.startswith("contentedit:"))
async def content_edit_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    content = await db.get_content(cid)
    if not content:
        await call.answer("Content not found.", show_alert=True); return
    await state.clear()
    await state.update_data(edit_content_id=cid)
    await state.set_state(EditContentInfo.title)
    await call.message.answer(f"Current title: {content['title']}\nSend the new title (1–100 characters):")
    await call.answer()

@router.message(EditContentInfo.title)
async def content_edit_title(message: Message, state: FSMContext):
    if not await require_owner(message): return
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer("Title must be 1–100 characters. Try again.")
        return
    await state.update_data(new_title=title)
    await state.set_state(EditContentInfo.description)
    await message.answer("Send the new description, or send - to clear it:")

@router.message(EditContentInfo.description)
async def content_edit_description(message: Message, state: FSMContext):
    if not await require_owner(message): return
    data = await state.get_data()
    description = "" if (message.text or "").strip() == "-" else (message.text or "").strip()[:500]
    await db.update_content_info(data["edit_content_id"], data["new_title"], description)
    await state.clear()
    await message.answer("✅ Content title and description updated.", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("contentprice:"))
async def content_price_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    cid = int(call.data.split(":")[1])
    await state.clear()
    await state.update_data(edit_content_id=cid)
    await state.set_state(EditContentPrice.value)
    await call.message.answer("Send new price (number in PKR) or type free:")
    await call.answer()

@router.message(EditContentPrice.value)
async def edit_content_price_value(message: Message, state: FSMContext):
    if not await require_owner(message): return
    data = await state.get_data()
    value = (message.text or "").strip().lower()
    if value == "free":
        price = 0
    else:
        try:
            price = float(value)
            if price <= 0 or price > 100000000: raise ValueError
        except ValueError:
            await message.answer("Send a valid positive amount in PKR or type free.")
            return
    await db.update_content_price(data["edit_content_id"], price)
    await state.clear()
    await message.answer("✅ Content price updated.", reply_markup=admin_menu())

@router.callback_query(F.data == "admin:channels")
async def channels_menu(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    rows = await db.get_channels(enabled_only=False)
    enabled = await db.get_setting("force_join_enabled", "1")
    toggle_label = "⏸ Disable Force Join" if enabled == "1" else "▶️ Enable Force Join"
    buttons = [[InlineKeyboardButton(text=f"🗑 Remove {c['title'][:30]}",
                                     callback_data=f"channeldelete:{c['id']}")] for c in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Channel", callback_data="channeladd")])
    buttons.insert(1, [InlineKeyboardButton(text=toggle_label, callback_data="forcetoggle")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.message.answer(f"🔒 <b>Force Join Management</b>\nStatus: {'ENABLED' if enabled == '1' else 'DISABLED'}\nBot must be admin in every required channel.", 
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@router.callback_query(F.data == "forcetoggle")
async def force_join_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    current = await db.get_setting("force_join_enabled", "1")
    new_value = "0" if current == "1" else "1"
    await db.set_setting("force_join_enabled", new_value)
    rows = await db.get_channels(enabled_only=False)
    toggle_label = "⏸ Disable Force Join" if new_value == "1" else "▶️ Enable Force Join"
    buttons = [[InlineKeyboardButton(text=f"🗑 Remove {c['title'][:30]}", callback_data=f"channeldelete:{c['id']}")] for c in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Channel", callback_data="channeladd")])
    buttons.insert(1, [InlineKeyboardButton(text=toggle_label, callback_data="forcetoggle")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.answer(f"Force Join {'enabled' if new_value == '1' else 'disabled'}.")
    await call.message.answer(f"🔒 <b>Force Join Management</b>\nStatus: {'ENABLED' if new_value == '1' else 'DISABLED'}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "channeladd")
async def channel_add_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await state.set_state(AddChannel.details)
    await call.message.answer(
        "Send channel details in this format:\n<code>@channelusername | https://t.me/channelusername</code>\n\n"
        "For private channels, use numeric chat ID and an invite link. Add the bot as an administrator first.")
    await call.answer()

@router.message(AddChannel.details)
async def channel_add_finish(message: Message, state: FSMContext):
    if not await require_owner(message): return
    raw = (message.text or "").split("|", 1)
    if len(raw) != 2:
        await message.answer("Format: @channelusername | https://t.me/channel")
        return
    chat_ref, join_url = raw[0].strip(), raw[1].strip()
    if not join_url.startswith("https://t.me/"):
        await message.answer("Join URL must be an https://t.me/ link.")
        return
    try:
        chat = await message.bot.get_chat(chat_ref)
        bot_member = await message.bot.get_chat_member(chat.id, (await message.bot.get_me()).id)
        if bot_member.status not in ("administrator", "creator"):
            await message.answer("Please promote the bot to administrator in that channel, then try again.")
            return
        await db.add_channel(str(chat.id), chat.title or chat.username or chat_ref, join_url)
    except Exception as exc:
        await message.answer(f"Could not add channel. Check the chat ID, invite link and bot admin permissions.\nDetails: {str(exc)[:200]}")
        return
    await state.clear()
    await message.answer(f"✅ Force-join channel added: <b>{chat.title}</b>", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("channeldelete:"))
async def channel_delete(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await db.delete_channel(int(call.data.split(":")[1]))
    rows = await db.get_channels(enabled_only=False)
    enabled = await db.get_setting("force_join_enabled", "1")
    toggle_label = "⏸ Disable Force Join" if enabled == "1" else "▶️ Enable Force Join"
    buttons = [[InlineKeyboardButton(text=f"🗑 Remove {c['title'][:30]}", callback_data=f"channeldelete:{c['id']}")] for c in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Channel", callback_data="channeladd")])
    buttons.insert(1, [InlineKeyboardButton(text=toggle_label, callback_data="forcetoggle")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.answer("Channel removed.")
    await call.message.answer(f"🔒 <b>Force Join Management</b>\nStatus: {'ENABLED' if enabled == '1' else 'DISABLED'}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "admin:methods")
async def payment_methods_menu(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    rows = await db.get_payment_methods(enabled_only=False)
    buttons = [[InlineKeyboardButton(text=f"{'✅' if m['enabled'] else '⏸'} {m['name']} · {m['account']}",
                                     callback_data=f"methodmanage:{m['id']}")] for m in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Payment Method", callback_data="methodadd")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.message.answer("💳 <b>Payment Details</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@router.callback_query(F.data == "methodadd")
async def method_add_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await state.set_state(AddPaymentMethod.name)
    await call.message.answer("Enter method name (e.g. JazzCash / Easypaisa):")
    await call.answer()

@router.message(AddPaymentMethod.name)
async def method_name(message: Message, state: FSMContext):
    if not await require_owner(message): return
    await state.update_data(name=(message.text or "").strip()[:50])
    await state.set_state(AddPaymentMethod.holder)
    await message.answer("Enter account holder name:")

@router.message(AddPaymentMethod.holder)
async def method_holder(message: Message, state: FSMContext):
    if not await require_owner(message): return
    await state.update_data(holder=(message.text or "").strip()[:100])
    await state.set_state(AddPaymentMethod.account)
    await message.answer("Enter account number / IBAN / wallet ID:")

@router.message(AddPaymentMethod.account)
async def method_account(message: Message, state: FSMContext):
    if not await require_owner(message): return
    await state.update_data(account=(message.text or "").strip()[:100])
    await state.set_state(AddPaymentMethod.instructions)
    await message.answer("Enter payment instructions (or - for none):")

@router.message(AddPaymentMethod.instructions)
async def method_instructions(message: Message, state: FSMContext):
    if not await require_owner(message): return
    data = await state.get_data()
    instructions = "" if (message.text or "").strip() == "-" else (message.text or "")[:500]
    await db.add_payment_method(data["name"], data["holder"], data["account"], instructions)
    await state.clear()
    await message.answer("✅ Payment method added.", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("methodmanage:"))
async def method_manage(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    mid = int(call.data.split(":")[1])
    rows = await db.get_payment_methods(enabled_only=False)
    m = next((r for r in rows if r["id"] == mid), None)
    if not m:
        await call.answer("Not found.", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Enable / Disable", callback_data=f"methodtoggle:{mid}")],
        [InlineKeyboardButton(text="Delete", callback_data=f"methoddelete:{mid}")],
        [InlineKeyboardButton(text="⬅️ Payment Methods", callback_data="admin:methods")]
    ])
    await call.message.answer(
        f"<b>{m['name']}</b>\nHolder: {m['holder']}\nAccount: <code>{m['account']}</code>\n"
        f"Instructions: {m['instructions'] or 'None'}\nEnabled: {bool(m['enabled'])}", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("methodtoggle:"))
async def method_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await db.toggle_payment_method(int(call.data.split(":")[1]))
    rows = await db.get_payment_methods(enabled_only=False)
    buttons = [[InlineKeyboardButton(text=f"{'✅' if m['enabled'] else '⏸'} {m['name']} · {m['account']}",
                                     callback_data=f"methodmanage:{m['id']}")] for m in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Payment Method", callback_data="methodadd")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.answer("Payment method updated.")
    await call.message.answer("💳 <b>Payment Details</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("methoddelete:"))
async def method_delete(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await db.delete_payment_method(int(call.data.split(":")[1]))
    rows = await db.get_payment_methods(enabled_only=False)
    buttons = [[InlineKeyboardButton(text=f"{'✅' if m['enabled'] else '⏸'} {m['name']} · {m['account']}",
                                     callback_data=f"methodmanage:{m['id']}")] for m in rows]
    buttons.insert(0, [InlineKeyboardButton(text="➕ Add Payment Method", callback_data="methodadd")])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")])
    await call.answer("Payment method removed/disabled.")
    await call.message.answer("💳 <b>Payment Details</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("method:"))
async def choose_method(call: CallbackQuery, state: FSMContext):
    missing = await check_join(call.bot, call.from_user.id)
    if missing:
        await call.message.answer("Join required channels:", reply_markup=join_keyboard(missing))
        await call.answer()
        return
    _, cid, mid = call.data.split(":")
    methods = await db.get_payment_methods()
    method = next((m for m in methods if m["id"] == int(mid)), None)
    content = await db.get_content(int(cid))
    if not method or not content:
        await call.answer("This option is unavailable.", show_alert=True); return
    await state.clear()
    await state.update_data(content_id=int(cid), method_id=int(mid))
    await state.set_state(SubmitPayment.proof)
    await call.message.answer(
        f"💳 <b>{method['name']}</b>\nAccount holder: {method['holder']}\n"
        f"Account: <code>{method['account']}</code>\n{method['instructions']}\n\n"
        f"Amount: <b>PKR {content['price']:,.0f}</b>\n\n"
        "After paying, send your transaction/reference ID as text, or send a screenshot/photo/document "
        "with the transaction ID written in its caption. Admin will manually verify your payment.")
    await call.answer()

@router.message(SubmitPayment.proof)
async def payment_proof(message: Message, state: FSMContext):
    user = message.from_user
    data = await state.get_data()
    ref = (message.caption or message.text or "").strip()
    if not ref:
        await message.answer("Please include the transaction/reference ID in your message or media caption.")
        return
    proof_type, proof_file_id = None, None
    if message.photo:
        proof_type, proof_file_id = "photo", message.photo[-1].file_id
    elif message.document:
        proof_type, proof_file_id = "document", message.document.file_id
    payment = await db.create_payment(user.id, data["content_id"], data["method_id"],
                                      ref[:250], proof_file_id, proof_type)
    await state.clear()
    await message.answer(f"✅ Payment request submitted.\nOrder: <code>{payment['order_code']}</code>\n"
                          "Your access will be enabled after admin verification.")
    content = await db.get_content(data["content_id"])
    method_rows = await db.get_payment_methods(enabled_only=False)
    method = next((m for m in method_rows if m["id"] == data["method_id"]), None)
    note = (f"🧾 <b>NEW PAYMENT REQUEST</b>\nOrder: <code>{payment['order_code']}</code>\n"
            f"User: <code>{user.id}</code> (@{user.username or 'no username'})\n"
            f"Content: {escape(content['title']) if content else 'Unknown'}\n"
            f"Amount: PKR {content['price']:,.0f}\nMethod: {method['name'] if method else 'Unknown'}\n"
            f"Reference: <code>{escape(ref[:250])}</code>")
    try:
        if proof_type == "photo":
            await message.bot.send_photo(OWNER_ID, proof_file_id, caption=note,
                                         reply_markup=payment_review_keyboard(payment["id"]))
        elif proof_type == "document":
            await message.bot.send_document(OWNER_ID, proof_file_id, caption=note,
                                            reply_markup=payment_review_keyboard(payment["id"]))
        else:
            await message.bot.send_message(OWNER_ID, note, reply_markup=payment_review_keyboard(payment["id"]))
    except Exception:
        log.exception("Could not notify owner about payment %s", payment["id"])

@router.callback_query(F.data.startswith("payment:"))
async def review_payment(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    _, action, raw_id = call.data.split(":")
    pid = int(raw_id)
    payment = await db.get_payment(pid)
    if not payment or payment["status"] != "pending":
        await call.answer("This payment was already reviewed or not found.", show_alert=True); return
    approved = action == "approve"
    await db.review_payment(pid, approved)
    if approved:
        c = await db.get_content(payment["content_id"])
        if c:
            try:
                await bot.send_message(payment["user_id"], "✅ <b>Payment approved!</b> Your content is unlocked.")
                await deliver_content(bot, payment["user_id"], c)
            except Exception:
                log.exception("Failed to deliver approved content")
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(f"✅ Payment {payment['order_code']} approved.")
    else:
        await bot.send_message(payment["user_id"],
                               f"❌ Payment request {payment['order_code']} was rejected. Please contact support if you need help.")
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(f"❌ Payment {payment['order_code']} rejected.")
    await call.answer("Review saved.")

@router.callback_query(F.data == "admin:pending")
async def pending_payments(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    rows = await db.fetchall("""
        SELECT p.*,u.first_name,c.title FROM payments p
        LEFT JOIN users u ON u.telegram_id=p.user_id
        LEFT JOIN contents c ON c.id=p.content_id
        WHERE p.status='pending' ORDER BY p.id DESC LIMIT 20
    """)
    if not rows:
        await call.message.answer("No pending payment requests.", reply_markup=back_admin())
    else:
        for p in rows:
            text = (f"🧾 <b>{p['order_code']}</b>\nUser: {p['first_name']} ({p['user_id']})\n"
                    f"Content: {escape(p['title'] or 'Deleted')}\nRef: <code>{escape(p['transaction_ref'])}</code>")
            await call.message.answer(text, reply_markup=payment_review_keyboard(p["id"]))
    await call.answer()

@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await state.set_state(Broadcast.message)
    await call.message.answer(
        "📢 Send the message/media you want to broadcast. You can send text, photo, video, document, audio or a forwarded message.\n"
        "The bot will show a confirmation before sending.")
    await call.answer()

@router.message(Broadcast.message)
async def broadcast_preview(message: Message, state: FSMContext):
    if not await require_owner(message): return
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    count = await db.count("users", "is_blocked=0")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm Broadcast", callback_data="broadcast:confirm"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="broadcast:cancel")
    ]])
    await message.answer(f"Preview captured.\nTarget users: <b>{count}</b>\nSend this message to all active users?",
                         reply_markup=kb)

@router.callback_query(F.data == "broadcast:cancel")
async def broadcast_cancel(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await call.message.answer("Broadcast cancelled.", reply_markup=admin_menu())
    await call.answer()

@router.callback_query(F.data == "broadcast:confirm")
async def broadcast_confirm(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    data = await state.get_data()
    if "message_id" not in data:
        await call.answer("Broadcast message not found. Start again.", show_alert=True); return
    await call.answer("Broadcast started.")
    await call.message.answer("📢 Broadcast is running. Please do not restart the bot.")
    users = await db.get_user_ids(active_only=True)
    sent = failed = 0
    for uid in users:
        try:
            await bot.copy_message(uid, data["from_chat_id"], data["message_id"])
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            try:
                await bot.copy_message(uid, data["from_chat_id"], data["message_id"])
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            failed += 1
            await db.set_blocked(uid, True)
        except TelegramBadRequest:
            failed += 1
        except Exception:
            failed += 1
            log.exception("Broadcast failed for user %s", uid)
    await db.save_broadcast(len(users), sent, failed)
    await state.clear()
    await call.message.answer(
        f"✅ <b>Broadcast completed</b>\nTotal: {len(users)}\nSent: {sent}\nFailed: {failed}",
        reply_markup=admin_menu())

@router.callback_query(F.data == "admin:settings")
async def settings_menu(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    welcome = await db.get_setting("welcome_text", WELCOME_TEXT)
    support = await db.get_setting("support_username", SUPPORT_USERNAME)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Change Welcome Message", callback_data="setting:welcome")],
        [InlineKeyboardButton(text="✏️ Change Support Username", callback_data="setting:support")],
        [InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")]
    ])
    await call.message.answer(
        f"⚙️ <b>Bot Settings</b>\nWelcome: {welcome[:150]}\nSupport: {support or 'Not set'}",
        reply_markup=kb)
    await call.answer()

@router.callback_query(F.data == "setting:welcome")
async def setting_welcome_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await state.set_state(SetBotSetting.value)
    await state.update_data(setting_key="welcome_text")
    await call.message.answer("Send the new welcome message. HTML formatting is supported.")
    await call.answer()

@router.callback_query(F.data == "setting:support")
async def setting_support_start(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    await state.clear()
    await state.set_state(SetBotSetting.value)
    await state.update_data(setting_key="support_username")
    await call.message.answer("Send support username (e.g. @legendhassanofficial) or - to clear.")
    await call.answer()

@router.message(SetBotSetting.value)
async def setting_text_handler(message: Message, state: FSMContext):
    if not await require_owner(message): return
    data = await state.get_data()
    if "setting_key" not in data:
        return
    value = (message.text or "").strip()
    if data["setting_key"] == "support_username" and value == "-":
        value = ""
    await db.set_setting(data["setting_key"], value)
    await state.clear()
    await message.answer("✅ Setting updated.", reply_markup=admin_menu())

@router.callback_query(F.data == "admin:backup")
async def admin_backup(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    try:
        payload = await db.export_backup()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        document = BufferedInputFile(payload, filename=f"legend_content_hub_backup_{stamp}.json")
        await call.message.answer_document(document, caption="💾 <b>Legend Content Hub PostgreSQL data export</b>\nKeep this file somewhere safe.")
        await call.answer("Backup sent.")
    except Exception:
        log.exception("PostgreSQL backup export failed")
        await call.answer("Backup failed. Check the worker logs.", show_alert=True)

@router.callback_query(F.data == "admin:web")
async def web_link(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    if BOT_PUBLIC_URL:
        await call.message.answer(f"🌐 Dashboard: {BOT_PUBLIC_URL}")
    else:
        await call.message.answer("Web dashboard runs on your server's WEB_PORT (default 8000). Set BOT_PUBLIC_URL in .env if you have a public HTTPS URL.")
    await call.answer()
