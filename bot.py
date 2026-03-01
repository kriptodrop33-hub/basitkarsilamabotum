import os
import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
TOKEN      = os.getenv("BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_IDS  = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
GROUP_ID   = int(os.getenv("GROUP_ID", "0"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# VERİ DEPOLAMA (RAM)
# ══════════════════════════════════════════════════════════════
airdrops: list = []
airdrop_counter = 0

daily_users:   set = set()
weekly_users:  set = set()
monthly_users: set = set()
all_time_users:set = set()
join_log: list = []

today       = datetime.now().date()
week_start  = today - timedelta(days=today.weekday())
month_start = today.replace(day=1)

posted_news: set = set()

# ══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def reset_periods():
    global today, week_start, month_start
    global daily_users, weekly_users, monthly_users
    now_date = datetime.now().date()
    if now_date != today:
        daily_users.clear(); today = now_date
    new_week = now_date - timedelta(days=now_date.weekday())
    if new_week != week_start:
        weekly_users.clear(); week_start = new_week
    new_month = now_date.replace(day=1)
    if new_month != month_start:
        monthly_users.clear(); month_start = new_month


def register_user(user):
    reset_periods()
    uid = user.id
    daily_users.add(uid); weekly_users.add(uid)
    monthly_users.add(uid); all_time_users.add(uid)
    join_log.append({"user_id": uid, "date": datetime.now().date(), "name": user.full_name})


def get_active_airdrops():
    now = datetime.now().date()
    result = []
    for a in airdrops:
        if a["durum"] != "aktif":
            continue
        try:
            if datetime.strptime(a["bitis"], "%d.%m.%Y").date() < now:
                a["durum"] = "bitti"
                continue
        except Exception:
            pass
        result.append(a)
    return result


def get_airdrop_by_id(aid: int):
    for a in airdrops:
        if a["id"] == aid:
            return a
    return None


def puan_yildiz(puan: float) -> str:
    tam  = int(puan)
    yar  = 1 if (puan - tam) >= 0.5 else 0
    bos  = 10 - tam - yar
    return "⭐" * tam + ("✨" if yar else "") + "☆" * bos


def puan_renk(puan: float) -> str:
    if puan >= 8: return "🟢"
    if puan >= 5: return "🟡"
    return "🔴"


def airdrop_card(a: dict, detay: bool = False) -> str:
    durum_icon = "✅" if a["durum"] == "aktif" else "❌"
    puan = a.get("puan", 0)
    s = [
        f"{durum_icon} *#{a['id']} — {a['isim']}*",
        f"{puan_renk(puan)} Puan: {puan}/10  {puan_yildiz(puan)}",
        f"💰 Ödül: {a['odül']}",
        f"📅 Başlangıç: {a.get('baslangic', '—')}",
        f"⏳ Bitiş: {a['bitis']}",
    ]
    if detay and a.get("aciklama"):
        s.append(f"📝 {a['aciklama']}")
    if a.get("kategori"):
        s.append(f"🏷 Kategori: {a['kategori']}")
    s.append(f"🔗 [Katıl]({a['link']})")
    return "\n".join(s)


# ══════════════════════════════════════════════════════════════
# MENÜLER
# ══════════════════════════════════════════════════════════════
def ana_menu_keyboard(is_adm: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🎁 Airdroplar",   callback_data="menu_airdrops"),
            InlineKeyboardButton("🏆 En İyiler",    callback_data="menu_topairdrops"),
        ],
        [
            InlineKeyboardButton("📊 İstatistik",   callback_data="menu_istatistik"),
            InlineKeyboardButton("📰 Haberler",     callback_data="menu_haberler"),
        ],
        [InlineKeyboardButton("❓ Yardım",          callback_data="menu_yardim")],
    ]
    if is_adm:
        rows.append([InlineKeyboardButton("⚙️ Admin Paneli", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def filtre_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Puan ≥ 8", callback_data="filtre_8"),
            InlineKeyboardButton("🟡 Puan ≥ 5", callback_data="filtre_5"),
            InlineKeyboardButton("📋 Tümü",     callback_data="filtre_0"),
        ],
        [
            InlineKeyboardButton("⏰ Bugün Bitiyor", callback_data="filtre_bugun"),
            InlineKeyboardButton("📅 Bu Hafta",      callback_data="filtre_hafta"),
        ],
        [InlineKeyboardButton("🔙 Ana Menü",         callback_data="menu_ana")],
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Nasıl Eklerim?", callback_data="admin_ekle_info"),
            InlineKeyboardButton("📋 Tüm Airdroplar", callback_data="admin_tumu"),
        ],
        [
            InlineKeyboardButton("📰 Haber Paylaş",   callback_data="admin_haber"),
            InlineKeyboardButton("📊 İstatistik",     callback_data="admin_istat"),
        ],
        [InlineKeyboardButton("🔙 Ana Menü",           callback_data="menu_ana")],
    ])


def get_welcome_message():
    text = (
        "🎉 *KriptoDropTR 🎁 Kanalımıza Hoş Geldiniz!* 🎉\n\n"
        "🚀 Güncel *Airdrop* fırsatlarından haberdar olmak için\n"
        "📢 *KriptoDropTR DUYURU 🔊* kanalımıza katılmayı\n"
        "🔔 Kanal bildirimlerini açmayı unutmayın!\n\n"
        "💎 Bol kazançlar dileriz!"
    )
    kb = [
        [InlineKeyboardButton("📢 KriptoDropTR DUYURU 🔊", url="https://t.me/kriptodropduyuru")],
        [InlineKeyboardButton("📜 Kurallar", url="https://t.me/kriptodropduyuru/46")],
        [InlineKeyboardButton("❓ SSS",      url="https://t.me/kriptodropduyuru/47")],
    ]
    return text, InlineKeyboardMarkup(kb)


# ══════════════════════════════════════════════════════════════
# OPENAI + HABER
# ══════════════════════════════════════════════════════════════
async def openai_ozet(metin: str) -> str:
    if not OPENAI_KEY:
        return metin[:400] + "..."
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Sen bir kripto para haber editörüsün. "
                    "Verilen haberi Türkçe olarak 3-4 cümleyle özetle. "
                    "Sade ve anlaşılır bir dil kullan. Sadece özet yaz."
                ),
            },
            {"role": "user", "content": metin},
        ],
        "max_tokens": 300,
        "temperature": 0.7,
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"OpenAI hata: {e}")
        return metin[:400]


async def fetch_crypto_news() -> list:
    url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
                return data.get("Data", [])[:10]
    except Exception as e:
        log.warning(f"Haber çekme hata: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# HANDLER — YENİ ÜYE
# ══════════════════════════════════════════════════════════════
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        register_user(member)
        text, markup = get_welcome_message()
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════
# KOMUT — /start
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    adm  = is_admin(user.id)
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            f"👋 Merhaba *{user.first_name}*!\n\n🤖 *KriptoDropTR Bot*'a hoş geldin.",
            parse_mode="Markdown",
            reply_markup=ana_menu_keyboard(adm)
        )
    else:
        text, markup = get_welcome_message()
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════
# KOMUT — /yardim
# ══════════════════════════════════════════════════════════════
async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    adm = is_admin(update.effective_user.id)
    text = (
        "📖 *KriptoDropTR Bot — Komutlar*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌐 *Genel:*\n"
        "/start — Ana menü\n"
        "/airdrops — Aktif airdroplar\n"
        "/topairdrops — Puan ≥ 8 olanlar\n"
        "/filtrele — Puana/tarihe göre filtrele\n"
        "/airdrop `<id>` — Detay görüntüle\n"
        "/haberler — Son kripto haberleri\n"
        "/istatistik — İstatistikler\n"
    )
    if adm:
        text += (
            "\n🔧 *Admin:*\n"
            "/airdropekle `İsim|Ödül|Başlangıç|Bitiş|Puan|Link|Kategori|Açıklama`\n"
            "/airdropduzenle `<id>|alan|değer`\n"
            "/airdropbitir `<id>` — Sonlandır\n"
            "/airdropsil `<id>` — Sil\n"
            "/airdroptumu — Tüm liste\n"
            "/haberler\\_paylas — Gruba AI haber paylaş\n"
            "/duyuru `<metin>` — Gruba duyuru\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("🏠 Ana Menü", callback_data="menu_ana")
                                    ]]))


# ══════════════════════════════════════════════════════════════
# KOMUT — /airdrops
# ══════════════════════════════════════════════════════════════
async def cmd_airdrops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aktif = get_active_airdrops()
    if not aktif:
        await update.message.reply_text("🎁 Şu an aktif airdrop yok.",
                                        reply_markup=InlineKeyboardMarkup([[
                                            InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                        ]]))
        return
    text = "🎁 *Aktif Airdrop Listesi*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n\n".join(airdrop_card(a) for a in aktif)
    text += f"\n\n📌 Toplam {len(aktif)} aktif airdrop"
    await update.message.reply_text(text, parse_mode="Markdown",
                                    disable_web_page_preview=True,
                                    reply_markup=filtre_keyboard())


# ══════════════════════════════════════════════════════════════
# KOMUT — /topairdrops
# ══════════════════════════════════════════════════════════════
async def cmd_top_airdrops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    min_p = 8.0
    if context.args:
        try: min_p = float(context.args[0])
        except: pass
    liste = sorted([a for a in get_active_airdrops() if a.get("puan", 0) >= min_p],
                   key=lambda x: x.get("puan", 0), reverse=True)
    if not liste:
        await update.message.reply_text(f"😕 Puan ≥ {min_p} olan aktif airdrop yok.")
        return
    text = f"🏆 *En İyi Airdroplar (Puan ≥ {min_p})*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n\n".join(airdrop_card(a) for a in liste)
    await update.message.reply_text(text, parse_mode="Markdown",
                                    disable_web_page_preview=True,
                                    reply_markup=filtre_keyboard())


# ══════════════════════════════════════════════════════════════
# KOMUT — /filtrele
# ══════════════════════════════════════════════════════════════
async def cmd_filtrele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 *Filtrele:*", parse_mode="Markdown",
                                    reply_markup=filtre_keyboard())


# ══════════════════════════════════════════════════════════════
# KOMUT — /airdrop <id>
# ══════════════════════════════════════════════════════════════
async def cmd_airdrop_detay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: `/airdrop <id>`", parse_mode="Markdown")
        return
    a = get_airdrop_by_id(int(context.args[0]))
    if not a:
        await update.message.reply_text("❌ Bulunamadı.")
        return
    await update.message.reply_text(airdrop_card(a, detay=True),
                                    parse_mode="Markdown", disable_web_page_preview=True,
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("🔗 Katıl", url=a["link"]),
                                        InlineKeyboardButton("🔙 Liste", callback_data="menu_airdrops"),
                                    ]]))


# ══════════════════════════════════════════════════════════════
# KOMUT — /haberler
# ══════════════════════════════════════════════════════════════
async def cmd_haberler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📰 Haberler alınıyor... ⏳")
    haberler = await fetch_crypto_news()
    if not haberler:
        await msg.edit_text("❌ Haberler alınamadı.")
        return
    await msg.delete()
    for h in haberler[:3]:
        ozet = await openai_ozet(h.get("body", h.get("title", "")))
        text = f"📰 *{h['title']}*\n\n📝 {ozet}\n\n🔗 [Devamını oku]({h['url']})"
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        await asyncio.sleep(0.5)


# ══════════════════════════════════════════════════════════════
# KOMUT — /istatistik
# ══════════════════════════════════════════════════════════════
async def cmd_istatistik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_periods()
    today_d = datetime.now().date()
    gun_dagilim = {}
    for entry in join_log:
        d = entry["date"]
        if (today_d - d).days < 7:
            label = d.strftime("%d.%m")
            gun_dagilim[label] = gun_dagilim.get(label, 0) + 1
    dagilim_str = ""
    for gun, sayi in sorted(gun_dagilim.items()):
        dagilim_str += f"  {gun}: {'█' * min(sayi, 15)} {sayi}\n"

    text = (
        "📊 *KriptoDropTR — İstatistikler*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 *Üyeler:*\n"
        f"  📅 Bugün: {len(daily_users)}\n"
        f"  📆 Bu Hafta: {len(weekly_users)}\n"
        f"  🗓 Bu Ay: {len(monthly_users)}\n"
        f"  🏆 Tüm Zamanlar: {len(all_time_users)}\n\n"
        "🎁 *Airdroplar:*\n"
        f"  ✅ Aktif: {len(get_active_airdrops())}\n"
        f"  ❌ Bitti: {len([a for a in airdrops if a['durum']=='bitti'])}\n"
        f"  📋 Toplam: {len(airdrops)}\n\n"
        "📈 *Son 7 Gün Katılım:*\n"
        f"{dagilim_str if dagilim_str else '  Henüz veri yok.'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup([[
                                        InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                    ]]))


# ══════════════════════════════════════════════════════════════
# ADMİN — /airdropekle
# Format: İsim | Ödül | Başlangıç | Bitiş | Puan | Link [| Kategori] [| Açıklama]
# ══════════════════════════════════════════════════════════════
async def cmd_airdrop_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komut sadece adminlere açıktır.")
        return
    global airdrop_counter

    ornek = (
        "📝 *Kullanım:*\n"
        "`/airdropekle İsim | Ödül | Başlangıç | Bitiş | Puan | Link | Kategori | Açıklama`\n\n"
        "📌 Tarih formatı: `GG.AA.YYYY`\n"
        "📌 Puan: `0`–`10` arası\n\n"
        "*Örnek:*\n"
        "`/airdropekle Layer3 | 50 USDT | 01.01.2025 | 31.03.2025 | 9 | https://layer3.xyz | DeFi | Görev tabanlı`"
    )
    if not context.args:
        await update.message.reply_text(ornek, parse_mode="Markdown")
        return

    parts = [p.strip() for p in " ".join(context.args).split("|")]
    if len(parts) < 6:
        await update.message.reply_text("❌ En az 6 alan gerekli.\n\n" + ornek, parse_mode="Markdown")
        return

    try:
        puan = float(parts[4])
        assert 0 <= puan <= 10
    except Exception:
        await update.message.reply_text("❌ Puan 0–10 arasında sayı olmalı.")
        return

    airdrop_counter += 1
    yeni = {
        "id"        : airdrop_counter,
        "isim"      : parts[0],
        "odül"      : parts[1],
        "baslangic" : parts[2],
        "bitis"     : parts[3],
        "puan"      : puan,
        "link"      : parts[5],
        "kategori"  : parts[6] if len(parts) > 6 else "",
        "aciklama"  : parts[7] if len(parts) > 7 else "",
        "durum"     : "aktif",
        "eklendi"   : datetime.now(),
    }
    airdrops.append(yeni)
    await update.message.reply_text(
        f"✅ *Airdrop Eklendi!*\n\n{airdrop_card(yeni, detay=True)}",
        parse_mode="Markdown", disable_web_page_preview=True
    )


# ══════════════════════════════════════════════════════════════
# ADMİN — /airdropduzenle <id> | alan | değer
# ══════════════════════════════════════════════════════════════
async def cmd_airdrop_duzenle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok.")
        return
    if not context.args:
        await update.message.reply_text(
            "Kullanım: `/airdropduzenle <id> | alan | yeni değer`\n"
            "Alanlar: `isim odül baslangic bitis puan link kategori aciklama`",
            parse_mode="Markdown"
        )
        return
    parts = [p.strip() for p in " ".join(context.args).split("|")]
    if len(parts) < 3 or not parts[0].isdigit():
        await update.message.reply_text("❌ Geçersiz format.")
        return
    a = get_airdrop_by_id(int(parts[0]))
    if not a:
        await update.message.reply_text("❌ Bulunamadı.")
        return
    alan, deger = parts[1].lower(), parts[2]
    if alan == "puan":
        try: deger = float(deger)
        except: await update.message.reply_text("❌ Puan sayı olmalı."); return
    if alan not in a:
        await update.message.reply_text(f"❌ Geçersiz alan: `{alan}`", parse_mode="Markdown")
        return
    a[alan] = deger
    await update.message.reply_text(
        f"✅ Güncellendi!\n\n{airdrop_card(a, detay=True)}",
        parse_mode="Markdown", disable_web_page_preview=True
    )


# ══════════════════════════════════════════════════════════════
# ADMİN — bitir / sil / tümü
# ══════════════════════════════════════════════════════════════
async def cmd_airdrop_bitir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok."); return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: `/airdropbitir <id>`", parse_mode="Markdown"); return
    a = get_airdrop_by_id(int(context.args[0]))
    if not a: await update.message.reply_text("❌ Bulunamadı."); return
    a["durum"] = "bitti"
    await update.message.reply_text(f"❌ *#{a['id']} — {a['isim']}* sonlandırıldı.", parse_mode="Markdown")


async def cmd_airdrop_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok."); return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: `/airdropsil <id>`", parse_mode="Markdown"); return
    a = get_airdrop_by_id(int(context.args[0]))
    if not a: await update.message.reply_text("❌ Bulunamadı."); return
    airdrops.remove(a)
    await update.message.reply_text(f"🗑 *#{a['id']} — {a['isim']}* silindi.", parse_mode="Markdown")


async def cmd_airdrop_tumu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok."); return
    if not airdrops:
        await update.message.reply_text("📋 Henüz hiç airdrop yok."); return
    text = "📋 *Tüm Airdroplar*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n\n".join(airdrop_card(a) for a in airdrops)
    text += f"\n\n✅ Aktif: {len(get_active_airdrops())}  |  Toplam: {len(airdrops)}"
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════
# ADMİN — /haberler_paylas
# ══════════════════════════════════════════════════════════════
async def cmd_haber_paylas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok."); return
    if GROUP_ID == 0:
        await update.message.reply_text("❌ `GROUP_ID` ayarlanmamış.", parse_mode="Markdown"); return
    msg = await update.message.reply_text("📰 Haberler alınıyor... ⏳")
    haberler = await fetch_crypto_news()
    yeni = [h for h in haberler if h["id"] not in posted_news]
    if not yeni:
        await msg.edit_text("ℹ️ Yeni haber yok."); return
    n = 0
    for h in yeni[:3]:
        ozet = await openai_ozet(h.get("body", h.get("title", "")))
        text = (
            f"📰 *{h['title']}*\n\n📝 {ozet}\n\n"
            f"🔗 [Devamını oku]({h['url']})\n\n━━━━━━━━━━━━━━\n🤖 @KriptoDropTR"
        )
        try:
            await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                           disable_web_page_preview=True)
            posted_news.add(h["id"]); n += 1
            await asyncio.sleep(1)
        except Exception as e:
            log.warning(f"Haber gönderilemedi: {e}")
    await msg.edit_text(f"✅ {n} haber gruba paylaşıldı.")


# ══════════════════════════════════════════════════════════════
# ADMİN — /duyuru
# ══════════════════════════════════════════════════════════════
async def cmd_duyuru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Yetki yok."); return
    if not context.args:
        await update.message.reply_text("Kullanım: `/duyuru <metin>`", parse_mode="Markdown"); return
    if GROUP_ID == 0:
        await update.message.reply_text("❌ `GROUP_ID` ayarlanmamış."); return
    metin = " ".join(context.args)
    text = f"📣 *DUYURU*\n━━━━━━━━━━━━━━\n\n{metin}\n\n━━━━━━━━━━━━━━\n🤖 @KriptoDropTR"
    await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown")
    await update.message.reply_text("✅ Duyuru gruba gönderildi.")


# ══════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    adm  = is_admin(q.from_user.id)
    await q.answer()

    if data == "menu_ana":
        await q.message.edit_text(
            "👋 *KriptoDropTR Bot*\n\nAşağıdan işlem seç:",
            parse_mode="Markdown", reply_markup=ana_menu_keyboard(adm)
        )

    elif data == "menu_airdrops":
        aktif = get_active_airdrops()
        if not aktif:
            text, kb = "🎁 Şu an aktif airdrop yok.", InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")]])
        else:
            text = "🎁 *Aktif Airdrop Listesi*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "\n\n".join(airdrop_card(a) for a in aktif)
            text += f"\n\n📌 Toplam {len(aktif)} aktif"
            kb = filtre_keyboard()
        await q.message.edit_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=kb)

    elif data == "menu_topairdrops":
        liste = sorted([a for a in get_active_airdrops() if a.get("puan", 0) >= 8],
                       key=lambda x: x.get("puan", 0), reverse=True)
        text = ("🏆 *En İyi Airdroplar (≥8)*\n━━━━━━━━━━━━━━━━━━━━━\n\n" +
                "\n\n".join(airdrop_card(a) for a in liste)) if liste else "😕 Puan ≥ 8 olan yok."
        await q.message.edit_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=filtre_keyboard())

    elif data.startswith("filtre_"):
        now   = datetime.now().date()
        aktif = get_active_airdrops()
        if data == "filtre_8":
            liste  = sorted([a for a in aktif if a.get("puan",0) >= 8], key=lambda x: x.get("puan",0), reverse=True)
            baslik = "🟢 Puan ≥ 8"
        elif data == "filtre_5":
            liste  = sorted([a for a in aktif if a.get("puan",0) >= 5], key=lambda x: x.get("puan",0), reverse=True)
            baslik = "🟡 Puan ≥ 5"
        elif data == "filtre_0":
            liste  = sorted(aktif, key=lambda x: x.get("puan",0), reverse=True)
            baslik = "📋 Tüm Aktif"
        elif data == "filtre_bugun":
            liste  = [a for a in aktif if _bitis_gun(a) == now]
            baslik = "⏰ Bugün Bitiyor"
        elif data == "filtre_hafta":
            liste  = [a for a in aktif if _bitis_gun(a) and ((_bitis_gun(a) - now).days) <= 7]
            baslik = "📅 Bu Hafta Bitiyor"
        else:
            liste, baslik = aktif, "Airdroplar"

        text = (
            f"🔍 *{baslik}*\n━━━━━━━━━━━━━━━━━━━━━\n\n" +
            "\n\n".join(airdrop_card(a) for a in liste) +
            f"\n\n📌 {len(liste)} airdrop"
        ) if liste else f"😕 *{baslik}* — sonuç yok."
        await q.message.edit_text(text, parse_mode="Markdown",
                                  disable_web_page_preview=True, reply_markup=filtre_keyboard())

    elif data == "menu_istatistik":
        reset_periods()
        text = (
            "📊 *İstatistikler*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Bugün: {len(daily_users)}  📆 Bu Hafta: {len(weekly_users)}\n"
            f"🗓 Bu Ay: {len(monthly_users)}  🏆 Toplam: {len(all_time_users)}\n\n"
            f"🎁 Aktif Airdrop: {len(get_active_airdrops())}  |  Toplam: {len(airdrops)}"
        )
        await q.message.edit_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                  ]]))

    elif data == "menu_haberler":
        await q.message.edit_text("📰 Haberler alınıyor... ⏳")
        haberler = await fetch_crypto_news()
        if not haberler:
            await q.message.edit_text("❌ Haberler alınamadı.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                      ]]))
            return
        h    = haberler[0]
        ozet = await openai_ozet(h.get("body", h.get("title", "")))
        text = f"📰 *{h['title']}*\n\n📝 {ozet}\n\n🔗 [Devamını oku]({h['url']})"
        await q.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True,
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                  ]]))

    elif data == "menu_yardim":
        text = (
            "📖 *Komutlar*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/airdrops — Aktif airdroplar\n/topairdrops — En iyiler\n"
            "/filtrele — Filtrele\n/airdrop `<id>` — Detay\n"
            "/haberler — Haberler\n/istatistik — İstatistik\n"
        )
        await q.message.edit_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                  ]]))

    elif data == "menu_admin":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        await q.message.edit_text("⚙️ *Admin Paneli*", parse_mode="Markdown",
                                  reply_markup=admin_keyboard())

    elif data == "admin_ekle_info":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        await q.message.edit_text(
            "➕ *Airdrop Ekle*\n\n"
            "`/airdropekle İsim | Ödül | Başlangıç | Bitiş | Puan | Link | Kategori | Açıklama`\n\n"
            "*Örnek:*\n"
            "`/airdropekle Layer3 | 50 USDT | 01.01.2025 | 31.03.2025 | 9 | https://layer3.xyz | DeFi | Görev tabanlı`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
            ]])
        )

    elif data == "admin_tumu":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        if not airdrops:
            text = "📋 Henüz airdrop yok."
        else:
            text = "📋 *Tüm Airdroplar*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "\n\n".join(airdrop_card(a) for a in airdrops)
            text += f"\n\n✅ Aktif: {len(get_active_airdrops())}  |  Toplam: {len(airdrops)}"
        await q.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True,
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                  ]]))

    elif data == "admin_haber":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        if GROUP_ID == 0:
            await q.message.edit_text("❌ GROUP_ID ayarlanmamış.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                      ]]))
            return
        await q.message.edit_text("📰 Haberler alınıyor ve özetleniyor... ⏳")
        haberler = await fetch_crypto_news()
        yeni = [h for h in haberler if h["id"] not in posted_news]
        n = 0
        for h in yeni[:3]:
            ozet = await openai_ozet(h.get("body", h.get("title", "")))
            text = (
                f"📰 *{h['title']}*\n\n📝 {ozet}\n\n"
                f"🔗 [Devamını oku]({h['url']})\n\n━━━━━━━━━━━━━━\n🤖 @KriptoDropTR"
            )
            try:
                await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                               disable_web_page_preview=True)
                posted_news.add(h["id"]); n += 1
                await asyncio.sleep(1)
            except Exception as e:
                log.warning(f"Haber gonderilemedi: {e}")
        await q.message.edit_text(f"✅ {n} haber paylaşıldı.",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                  ]]))

    elif data == "admin_istat":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        reset_periods()
        text = (
            "📊 *Detaylı İstatistik*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 Bugün: {len(daily_users)}\n📆 Bu Hafta: {len(weekly_users)}\n"
            f"🗓 Bu Ay: {len(monthly_users)}\n🏆 Tüm Zamanlar: {len(all_time_users)}\n\n"
            f"✅ Aktif Airdrop: {len(get_active_airdrops())}\n"
            f"❌ Bitti: {len([a for a in airdrops if a['durum']=='bitti'])}\n"
            f"📋 Toplam: {len(airdrops)}\n\n"
            f"📰 Paylaşılan Haber: {len(posted_news)}"
        )
        await q.message.edit_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                  ]]))


def _bitis_gun(a):
    try:
        return datetime.strptime(a["bitis"], "%d.%m.%Y").date()
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# OTOMATİK HABER (her 6 saatte bir)
# ══════════════════════════════════════════════════════════════
async def auto_haber_job(context: ContextTypes.DEFAULT_TYPE):
    if GROUP_ID == 0 or not OPENAI_KEY:
        return
    haberler = await fetch_crypto_news()
    yeni = [h for h in haberler if h["id"] not in posted_news]
    for h in yeni[:2]:
        ozet = await openai_ozet(h.get("body", h.get("title", "")))
        text = (
            f"📰 *{h['title']}*\n\n📝 {ozet}\n\n"
            f"🔗 [Devamını oku]({h['url']})\n\n━━━━━━━━━━━━━━\n🤖 @KriptoDropTR"
        )
        try:
            await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                           disable_web_page_preview=True)
            posted_news.add(h["id"])
            await asyncio.sleep(2)
        except Exception as e:
            log.warning(f"Oto haber hatasi: {e}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start",        "Ana menü"),
        BotCommand("airdrops",     "Aktif airdroplar"),
        BotCommand("topairdrops",  "En iyi airdroplar (≥8 puan)"),
        BotCommand("filtrele",     "Puana/tarihe göre filtrele"),
        BotCommand("haberler",     "Son kripto haberleri"),
        BotCommand("istatistik",   "Grup istatistikleri"),
        BotCommand("yardim",       "Yardım ve komutlar"),
    ])
    log.info("Komutlar ayarlandı.")


def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.job_queue.run_repeating(auto_haber_job, interval=21600, first=300)

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    app.add_handler(CommandHandler("start",           cmd_start))
    app.add_handler(CommandHandler("yardim",          cmd_yardim))
    app.add_handler(CommandHandler("airdrops",        cmd_airdrops))
    app.add_handler(CommandHandler("topairdrops",     cmd_top_airdrops))
    app.add_handler(CommandHandler("filtrele",        cmd_filtrele))
    app.add_handler(CommandHandler("airdrop",         cmd_airdrop_detay))
    app.add_handler(CommandHandler("haberler",        cmd_haberler))
    app.add_handler(CommandHandler("istatistik",      cmd_istatistik))

    app.add_handler(CommandHandler("airdropekle",     cmd_airdrop_ekle))
    app.add_handler(CommandHandler("airdropduzenle",  cmd_airdrop_duzenle))
    app.add_handler(CommandHandler("airdropbitir",    cmd_airdrop_bitir))
    app.add_handler(CommandHandler("airdropsil",      cmd_airdrop_sil))
    app.add_handler(CommandHandler("airdroptumu",     cmd_airdrop_tumu))
    app.add_handler(CommandHandler("haberler_paylas", cmd_haber_paylas))
    app.add_handler(CommandHandler("duyuru",          cmd_duyuru))

    app.add_handler(CallbackQueryHandler(button_handler))

    log.info("KriptoDropTR Bot v3 Aktif 🚀")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
