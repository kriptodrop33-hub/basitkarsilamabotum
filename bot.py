import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters
)
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")

# ──────────────────────────────────────────────────────────────
# İSTATİSTİK VERİLERİ
# ──────────────────────────────────────────────────────────────
daily_users   : set   = set()    # bugün katılanlar (ID seti)
weekly_users  : set   = set()    # bu hafta katılanlar
monthly_users : set   = set()    # bu ay katılanlar
all_time_users: set   = set()    # tüm zamanlar

today         = datetime.now().date()
week_start    = today - timedelta(days=today.weekday())
month_start   = today.replace(day=1)

join_log: list[dict] = []   # {"user_id": int, "date": date, "name": str}

# ──────────────────────────────────────────────────────────────
# AİRDROP LİSTESİ
# Her kayıt: {"id": int, "isim": str, "link": str, "bitis": str,
#             "odül": str, "durum": str, "eklendi": datetime}
# ──────────────────────────────────────────────────────────────
airdrops: list[dict] = []
airdrop_counter = 0   # otomatik ID


# ──────────────────────────────────────────────────────────────
# YARDIMCILAR
# ──────────────────────────────────────────────────────────────
def reset_periods():
    """Günlük / haftalık / aylık periyotları gerekirse sıfırla."""
    global today, week_start, month_start
    global daily_users, weekly_users, monthly_users

    now_date = datetime.now().date()

    if now_date != today:
        daily_users.clear()
        today = now_date

    new_week = now_date - timedelta(days=now_date.weekday())
    if new_week != week_start:
        weekly_users.clear()
        week_start = new_week

    new_month = now_date.replace(day=1)
    if new_month != month_start:
        monthly_users.clear()
        month_start = new_month


def register_user(user):
    """Yeni katılan kullanıcıyı tüm istatistik setlerine ekle."""
    reset_periods()
    uid = user.id
    daily_users.add(uid)
    weekly_users.add(uid)
    monthly_users.add(uid)
    all_time_users.add(uid)
    join_log.append({
        "user_id": uid,
        "date"   : datetime.now().date(),
        "name"   : user.full_name,
    })


def get_active_airdrops():
    return [a for a in airdrops if a["durum"] == "aktif"]


def get_airdrop_by_id(aid: int):
    for a in airdrops:
        if a["id"] == aid:
            return a
    return None


def airdrop_card(a: dict) -> str:
    """Tek bir airdrop için özet metin."""
    durum_icon = "✅" if a["durum"] == "aktif" else "❌"
    return (
        f"{durum_icon} *#{a['id']} — {a['isim']}*\n"
        f"💰 Ödül: {a['odül']}\n"
        f"⏳ Bitiş: {a['bitis']}\n"
        f"🔗 [Katıl]({a['link']})"
    )


# ──────────────────────────────────────────────────────────────
# HOŞ GELDİN MESAJI
# ──────────────────────────────────────────────────────────────
def get_welcome_message():
    welcome_text = (
        "🎉 *KriptoDropTR 🎁 Kanalımıza Hoş Geldiniz!* 🎉\n\n"
        "🚀 Güncel *Airdrop* fırsatlarından haberdar olmak için\n\n"
        "📢 *KriptoDropTR DUYURU 🔊* kanalımıza katılmayı\n"
        "🔔 Kanal bildirimlerini açmayı unutmayın!\n\n"
        "💎 Bol kazançlar dileriz!"
    )
    keyboard = [
        [InlineKeyboardButton("📢 KriptoDropTR DUYURU 🔊 KANALI", url="https://t.me/kriptodropduyuru")],
        [InlineKeyboardButton("📜 Kurallar",                       url="https://t.me/kriptodropduyuru/46")],
        [InlineKeyboardButton("❓ Sık Sorulan Sorular (SSS)",      url="https://t.me/kriptodropduyuru/47")],
    ]
    return welcome_text, InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────────────────────────
# HANDLERS — YENİ ÜYE
# ──────────────────────────────────────────────────────────────
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        register_user(member)
        text, markup = get_welcome_message()
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────
# HANDLERS — ÖZEL MESAJ
# ──────────────────────────────────────────────────────────────
async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = get_welcome_message()
    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — İSTATİSTİK
# ──────────────────────────────────────────────────────────────
async def cmd_istatistik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /istatistik — Günlük / haftalık / aylık / tüm zamanlar katılım özeti.
    Gruba veya DM'e yazılabilir.
    """
    reset_periods()

    # Son 7 günlük günlük dağılım
    today_d = datetime.now().date()
    gun_dagilim = {}
    for entry in join_log:
        d = entry["date"]
        if (today_d - d).days < 7:
            label = d.strftime("%d.%m")
            gun_dagilim[label] = gun_dagilim.get(label, 0) + 1

    dagilim_str = ""
    for gun, sayi in sorted(gun_dagilim.items()):
        bar = "█" * min(sayi, 20)
        dagilim_str += f"  {gun}: {bar} {sayi}\n"

    text = (
        "📊 *KriptoDropTR — Katılım İstatistikleri*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Bugün:*      {len(daily_users)} kişi\n"
        f"📆 *Bu Hafta:*   {len(weekly_users)} kişi\n"
        f"🗓 *Bu Ay:*      {len(monthly_users)} kişi\n"
        f"🏆 *Tüm Zamanlar:* {len(all_time_users)} kişi\n\n"
        "📈 *Son 7 Gün (Günlük Dağılım):*\n"
        f"{dagilim_str if dagilim_str else '  Henüz veri yok.'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — AİRDROP LİSTESİ (genel)
# ──────────────────────────────────────────────────────────────
async def cmd_airdrops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /airdrops — Aktif airdrop listesini göster.
    """
    aktif = get_active_airdrops()
    if not aktif:
        await update.message.reply_text("🎁 Şu an aktif airdrop bulunmuyor.")
        return

    text = "🎁 *Aktif Airdrop Listesi*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n\n".join(airdrop_card(a) for a in aktif)
    text += f"\n\n📌 Toplam {len(aktif)} aktif airdrop"

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — AİRDROP EKLE (admin)
# ──────────────────────────────────────────────────────────────
async def cmd_airdrop_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /airdropekle <isim> | <ödül> | <bitiş tarihi> | <link>
    Örnek: /airdropekle Layer3 | 50 USDT | 31.12.2025 | https://layer3.xyz
    """
    global airdrop_counter

    if not context.args:
        await update.message.reply_text(
            "📝 *Kullanım:*\n"
            "`/airdropekle İsim | Ödül | Bitiş Tarihi | Link`\n\n"
            "Örnek:\n"
            "`/airdropekle Layer3 | 50 USDT | 31.12.2025 | https://layer3.xyz`",
            parse_mode="Markdown"
        )
        return

    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) < 4:
        await update.message.reply_text(
            "❌ Eksik bilgi. 4 alan gerekli: `İsim | Ödül | Bitiş | Link`",
            parse_mode="Markdown"
        )
        return

    airdrop_counter += 1
    yeni = {
        "id"     : airdrop_counter,
        "isim"   : parts[0],
        "odül"   : parts[1],
        "bitis"  : parts[2],
        "link"   : parts[3],
        "durum"  : "aktif",
        "eklendi": datetime.now(),
    }
    airdrops.append(yeni)

    await update.message.reply_text(
        f"✅ *Airdrop Eklendi!*\n\n{airdrop_card(yeni)}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — AİRDROP BİTİR (admin)
# ──────────────────────────────────────────────────────────────
async def cmd_airdrop_bitir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /airdropbitir <id>  → Airdropi pasif yap.
    """
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: `/airdropbitir <id>`", parse_mode="Markdown")
        return

    aid = int(context.args[0])
    a   = get_airdrop_by_id(aid)

    if not a:
        await update.message.reply_text(f"❌ #{aid} ID'li airdrop bulunamadı.")
        return

    a["durum"] = "bitti"
    await update.message.reply_text(
        f"❌ *#{a['id']} — {a['isim']}* airdropu sonlandırıldı.",
        parse_mode="Markdown"
    )


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — AİRDROP SİL (admin)
# ──────────────────────────────────────────────────────────────
async def cmd_airdrop_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /airdropsil <id>  → Listeden tamamen kaldır.
    """
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: `/airdropsil <id>`", parse_mode="Markdown")
        return

    aid = int(context.args[0])
    a   = get_airdrop_by_id(aid)

    if not a:
        await update.message.reply_text(f"❌ #{aid} ID'li airdrop bulunamadı.")
        return

    airdrops.remove(a)
    await update.message.reply_text(f"🗑 *#{aid} — {a['isim']}* listeden silindi.", parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — TÜM AİRDROPLAR (admin, bitti dahil)
# ──────────────────────────────────────────────────────────────
async def cmd_airdrop_tumu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /airdroptumu — Aktif + bitmiş tüm airdropları göster (admin).
    """
    if not airdrops:
        await update.message.reply_text("📋 Henüz hiç airdrop eklenmedi.")
        return

    text = "📋 *Tüm Airdroplar*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n\n".join(airdrop_card(a) for a in airdrops)
    text += f"\n\n✅ Aktif: {len(get_active_airdrops())}  |  Toplam: {len(airdrops)}"

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


# ──────────────────────────────────────────────────────────────
# KOMUTLAR — YARDIM
# ──────────────────────────────────────────────────────────────
async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *KriptoDropTR Bot — Komutlar*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌐 *Herkes kullanabilir:*\n"
        "/airdrops — Aktif airdrop listesi\n"
        "/istatistik — Katılım istatistikleri\n"
        "/yardim — Bu yardım mesajı\n\n"
        "🔧 *Admin komutları:*\n"
        "/airdropekle İsim | Ödül | Bitiş | Link\n"
        "/airdropbitir \\<id\\> — Airdropi sonlandır\n"
        "/airdropsil \\<id\\> — Listeden sil\n"
        "/airdroptumu — Tüm airdropları gör\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")




# ──────────────────────────────────────────────────────────────
# KOMUTLAR — START
# ──────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = get_welcome_message()
    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

# ──────────────────────────────────────────────────────────────
# UYGULAMA
# ──────────────────────────────────────────────────────────────
app = ApplicationBuilder().token(TOKEN).build()

# Yeni üye & DM
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_message))

# Genel komutlar
app.add_handler(CommandHandler("start",       cmd_start))
app.add_handler(CommandHandler("airdrops",    cmd_airdrops))
app.add_handler(CommandHandler("istatistik",  cmd_istatistik))
app.add_handler(CommandHandler("yardim",      cmd_yardim))

# Admin komutları
app.add_handler(CommandHandler("airdropekle",  cmd_airdrop_ekle))
app.add_handler(CommandHandler("airdropbitir", cmd_airdrop_bitir))
app.add_handler(CommandHandler("airdropsil",   cmd_airdrop_sil))
app.add_handler(CommandHandler("airdroptumu",  cmd_airdrop_tumu))

if __name__ == "__main__":
    print("KriptoDropTR Bot v2 Aktif 🚀")
    app.run_polling(drop_pending_updates=True)
