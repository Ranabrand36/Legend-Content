from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Browse Content", callback_data="user:browse")],
        [InlineKeyboardButton(text="🆓 Free Content", callback_data="user:free"),
         InlineKeyboardButton(text="💎 Premium Content", callback_data="user:paid")],
        [InlineKeyboardButton(text="🛒 My Purchases", callback_data="user:purchases")],
        [InlineKeyboardButton(text="👤 My Account", callback_data="user:account"),
         InlineKeyboardButton(text="📞 Support", callback_data="user:support")],
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Dashboard / Stats", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast"),
         InlineKeyboardButton(text="📁 Add Content", callback_data="admin:add")],
        [InlineKeyboardButton(text="🗂 Manage Content", callback_data="admin:contents")],
        [InlineKeyboardButton(text="🔒 Force Join", callback_data="admin:channels")],
        [InlineKeyboardButton(text="💳 Payment Details", callback_data="admin:methods")],
        [InlineKeyboardButton(text="🧾 Pending Payments", callback_data="admin:pending")],
        [InlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin:settings")],
        [InlineKeyboardButton(text="💾 Database Backup", callback_data="admin:backup")],
        [InlineKeyboardButton(text="🌐 Open Web Dashboard", callback_data="admin:web")],
    ])

def back_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin:home")]
    ])

def join_keyboard(channels, code=""):
    rows = [[InlineKeyboardButton(text=f"Join: {c['title'][:50]}", url=c["join_url"])]
            for c in channels]
    rows.append([InlineKeyboardButton(text="✅ I've Joined — Verify", callback_data=f"verify:{code or 'home'}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def content_keyboard(content):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Get Content Link", callback_data=f"link:{content['id']}")],
        [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="user:home")]
    ])

def payment_method_keyboard(methods, content_id):
    rows = [[InlineKeyboardButton(text=f"{m['name']}", callback_data=f"method:{content_id}:{m['id']}")]
            for m in methods]
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"content:{content_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def payment_review_keyboard(payment_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"payment:approve:{payment_id}"),
         InlineKeyboardButton(text="❌ Reject", callback_data=f"payment:reject:{payment_id}")]
    ])
