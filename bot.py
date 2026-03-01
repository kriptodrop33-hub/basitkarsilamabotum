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

# Haber sistemi ayarları (RAM — bot yeniden başlayınca sıfırlanır)
# Bu ayarları Railway Variables ile kalıcı hale getirebilirsin
haber_ayarlari: dict = {
    "aktif"        : True,
    "interval_saat": 6,
    "adet"         : 2,
    "son_dk_aktif" : True,
    "son_dk_esik"  : 15,
    "kanal_tag"    : "@KriptoDropTR",
}

# Son dakika haberi için son kontrol zamanı
son_dk_kontrol: datetime = datetime.now()

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
# OPENAI — Özet + Başlık Çevirisi
# ══════════════════════════════════════════════════════════════
async def openai_ozet(metin: str, baslik: str = "") -> dict:
    """
    Haberi Türkçe olarak özetler ve başlığı çevirir.
    Döndürdüğü dict: {"baslik": str, "ozet": str, "son_dk": bool, "etiketler": list}
    """
    if not OPENAI_KEY:
        return {"baslik": baslik, "ozet": metin[:300] + "...", "son_dk": False, "etiketler": []}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}

    prompt = (
        "Sana Türkçe bir kripto para haberi veriyorum. Şunları yap:\n\n"
        "1. Başlığı düzenle: Zaten Türkçeyse sadece kısa ve vurucu hale getir\n"
        "2. Haberi Türkçe olarak 3-5 cümleyle özetle. "
        "Sade, akıcı, heyecan verici dil kullan. "
        "Teknik detayları sadeleştir. Okuyucuya ne anlama geldiğini açıkla.\n"
        "3. Bu haber 'SON DAKİKA' niteliğinde mi? "
        "Evet kriterleri: büyük borsa hack/iflas, ülke kararı (yasak/kabul), "
        "SEC/regülasyon kararı, BTC/ETH %5+ ani hareket, büyük whale işlemi. "
        "Rutin haber, fiyat tahmini, analiz = false.\n"
        "4. İlgili kripto etiketleri (max 3, örn: #BTC #ETH #SOL)\n\n"
        "Yanıtı SADECE JSON formatında ver, başka hiç bir şey yazma:\n"
        "{\"baslik\": \"kısa başlık\", \"ozet\": \"özet metin\", \"son_dk\": false, \"etiketler\": [\"#BTC\"]}\n\n"
        f"--- HABER BAŞLIĞI ---\n{baslik}\n\n"
        f"--- HABER İÇERİĞİ ---\n{metin[:1500]}"
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=25)) as r:
                data = await r.json()
                import json as _json
                result = _json.loads(data["choices"][0]["message"]["content"])
                return {
                    "baslik"   : result.get("baslik", baslik),
                    "ozet"     : result.get("ozet", metin[:300]),
                    "son_dk"   : bool(result.get("son_dk", False)),
                    "etiketler": result.get("etiketler", []),
                }
    except Exception as e:
        log.warning(f"OpenAI hata: {e}")
        return {"baslik": baslik, "ozet": metin[:300] + "...", "son_dk": False, "etiketler": []}


# ══════════════════════════════════════════════════════════════
# HABER KAYNAKLARI — İngilizce + Türkçe
# ══════════════════════════════════════════════════════════════
# Sadece Türkçe kaynaklar — İngilizce kaynak yok
# AI özeti zaten Türkçe yapıyor, Türkçe sitelerden haber çekince çeviri kalitesi artar
HABER_KAYNAKLARI = [
    {
        "url"  : "https://api.rss2json.com/v1/api.json?rss_url=https://www.btchaber.com/feed/",
        "tip"  : "rss2json",
        "dil"  : "tr",
        "isim" : "BTCHaber",
    },
    {
        "url"  : "https://api.rss2json.com/v1/api.json?rss_url=https://kriptokoin.com/feed/",
        "tip"  : "rss2json",
        "dil"  : "tr",
        "isim" : "KriptoKoin",
    },
    {
        "url"  : "https://api.rss2json.com/v1/api.json?rss_url=https://cointurk.com/feed",
        "tip"  : "rss2json",
        "dil"  : "tr",
        "isim" : "CoinTurk",
    },
    {
        "url"  : "https://api.rss2json.com/v1/api.json?rss_url=https://tr.cointelegraph.com/rss",
        "tip"  : "rss2json",
        "dil"  : "tr",
        "isim" : "CoinTelegraph TR",
    },
    {
        "url"  : "https://api.rss2json.com/v1/api.json?rss_url=https://kriptopara.com/feed/",
        "tip"  : "rss2json",
        "dil"  : "tr",
        "isim" : "KriptoPara",
    },
]


def _parse_rss_date(tarih_str: str) -> datetime:
    for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"]:
        try:
            return datetime.strptime(tarih_str, fmt).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.utcnow()


async def fetch_tek_kaynak(sess: aiohttp.ClientSession, kaynak: dict) -> list:
    try:
        async with sess.get(kaynak["url"], timeout=aiohttp.ClientTimeout(total=12)) as r:
            data = await r.json(content_type=None)
        haberler = []
        for h in data.get("items", [])[:10]:
            link  = h.get("link", "")
            guid  = h.get("guid", link)
            baslik = h.get("title", "").strip()
            # HTML taglarını temizle (description bazen HTML içeriyor)
            import re as _re
            icerik_ham = h.get("description", h.get("content", ""))
            icerik = _re.sub(r"<[^>]+>", " ", icerik_ham).strip()[:1200]
            haberler.append({
                "id"    : guid,
                "baslik": baslik,
                "icerik": icerik,
                "url"   : link,
                "kaynak": kaynak["isim"],
                "dil"   : "tr",
                "zaman" : _parse_rss_date(h.get("pubDate", "")),
            })
        return haberler
    except Exception as e:
        log.warning(f"Kaynak {kaynak['isim']} hata: {e}")
        return []


async def fetch_crypto_news() -> list:
    """Tüm kaynaklardan haberleri çeker, birleştirir, sıralar."""
    async with aiohttp.ClientSession() as sess:
        tasks = [fetch_tek_kaynak(sess, k) for k in HABER_KAYNAKLARI]
        sonuclar = await asyncio.gather(*tasks)
    tum = []
    for liste in sonuclar:
        tum.extend(liste)
    gorulmus = set()
    temiz = []
    for h in tum:
        if h["url"] not in gorulmus:
            gorulmus.add(h["url"])
            temiz.append(h)
    temiz.sort(key=lambda x: x["zaman"], reverse=True)
    return temiz[:20]


def haber_mesaj_formatla(h: dict, ai: dict, son_dk: bool = False) -> str:
    """Telegram'a gönderilecek haber metnini oluşturur."""
    etiketler = " ".join(ai.get("etiketler", []))
    header = "🚨 *SON DAKİKA* 🚨" if son_dk else "📰 *Kripto Haber*"
    zaman_str = h["zaman"].strftime("%d.%m.%Y %H:%M") if h.get("zaman") else ""
    text = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{ai['baslik']}*\n\n"
        f"📝 {ai['ozet']}\n\n"
        f"🇹🇷 Kaynak: {h['kaynak']}  🕐 {zaman_str}\n"
        f"🔗 [Haberin tamamı]({h['url']})\n"
    )
    if etiketler:
        text += f"\n{etiketler}\n"
    text += f"\n━━━━━━━━━━━━━━\n🤖 {haber_ayarlari['kanal_tag']}"
    return text



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
            "/haberayar — Haber sistemi ayarları\n"
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
    msg = await update.message.reply_text("📰 Haberler alınıyor ve özetleniyor... ⏳")
    haberler = await fetch_crypto_news()
    if not haberler:
        await msg.edit_text("❌ Haberler alınamadı.")
        return
    await msg.delete()
    for h in haberler[:3]:
        ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
        son_dk = ai.get("son_dk", False)
        text = haber_mesaj_formatla(h, ai, son_dk=son_dk)
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        await asyncio.sleep(0.8)


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

    msg = await update.message.reply_text("📰 Haberler alınıyor ve özetleniyor... ⏳")
    haberler = await fetch_crypto_news()
    yeni = [h for h in haberler if h["id"] not in posted_news and h["url"] not in posted_news]
    if not yeni:
        await msg.edit_text("ℹ️ Yeni haber yok. Tüm haberler zaten paylaşıldı."); return

    # İlk yeni haberi al ve özetle
    h  = yeni[0]
    ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
    text = haber_mesaj_formatla(h, ai, son_dk=ai.get("son_dk", False))

    # ── ÖNİZLEME: Adminin DM'ine göster ──
    onizleme = (
        "👁 *HABER ÖNİZLEME*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Aşağıdaki haber gruba gönderilecek.\n"
        "Onaylamak için butona bas:\n\n"
        + text
    )
    # Haberi context.bot_data'ya geçici kaydet
    context.bot_data["bekleyen_haber_text"] = text
    context.bot_data["bekleyen_haber_id"]   = h["id"]
    context.bot_data["bekleyen_haber_url"]  = h["url"]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Gruba Gönder", callback_data="haber_onayla"),
            InlineKeyboardButton("❌ İptal",        callback_data="haber_iptal"),
        ],
        [
            InlineKeyboardButton("⏭ Sonraki Haber", callback_data="haber_sonraki"),
        ]
    ])
    await msg.delete()
    await update.message.reply_text(onizleme, parse_mode="Markdown",
                                    disable_web_page_preview=True,
                                    reply_markup=kb)


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
        await q.message.edit_text("📰 Haberler alınıyor ve özetleniyor... ⏳")
        haberler = await fetch_crypto_news()
        if not haberler:
            await q.message.edit_text("❌ Haberler alınamadı.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Menü", callback_data="menu_ana")
                                      ]]))
            return
        h  = haberler[0]
        ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
        text = haber_mesaj_formatla(h, ai, son_dk=ai.get("son_dk", False))
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
        yeni = [h for h in haberler if h["id"] not in posted_news and h["url"] not in posted_news]
        if not yeni:
            await q.message.edit_text("ℹ️ Yeni haber yok.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                      ]]))
            return
        h  = yeni[0]
        ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
        text = haber_mesaj_formatla(h, ai, son_dk=ai.get("son_dk", False))
        # Geçici kaydet
        context.bot_data["bekleyen_haber_text"] = text
        context.bot_data["bekleyen_haber_id"]   = h["id"]
        context.bot_data["bekleyen_haber_url"]  = h["url"]
        onizleme = "👁 *HABER ÖNİZLEME*\n━━━━━━━━━━━━━━━━━━━━\nGruba gönderilecek haber:\n\n" + text
        await q.message.edit_text(onizleme, parse_mode="Markdown",
                                  disable_web_page_preview=True,
                                  reply_markup=InlineKeyboardMarkup([
                                      [
                                          InlineKeyboardButton("✅ Gruba Gönder", callback_data="haber_onayla"),
                                          InlineKeyboardButton("❌ İptal",        callback_data="haber_iptal"),
                                      ],
                                      [InlineKeyboardButton("⏭ Sonraki Haber",   callback_data="haber_sonraki")],
                                  ]))

    elif data == "haber_onayla":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        text = context.bot_data.get("bekleyen_haber_text")
        hid  = context.bot_data.get("bekleyen_haber_id")
        hurl = context.bot_data.get("bekleyen_haber_url")
        if not text:
            await q.answer("⚠️ Haber bulunamadı, tekrar dene.", show_alert=True); return
        try:
            await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                           disable_web_page_preview=True)
            if hid:  posted_news.add(hid)
            if hurl: posted_news.add(hurl)
            context.bot_data.pop("bekleyen_haber_text", None)
            context.bot_data.pop("bekleyen_haber_id", None)
            context.bot_data.pop("bekleyen_haber_url", None)
            await q.message.edit_text("✅ Haber gruba gönderildi!",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                      ]]))
        except Exception as e:
            await q.message.edit_text(f"❌ Gönderilemedi: {e}",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                      ]]))

    elif data == "haber_iptal":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        context.bot_data.pop("bekleyen_haber_text", None)
        context.bot_data.pop("bekleyen_haber_id", None)
        context.bot_data.pop("bekleyen_haber_url", None)
        await q.message.edit_text("❌ Haber paylaşımı iptal edildi.",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                  ]]))

    elif data == "haber_sonraki":
        if not adm: await q.answer("⛔ Yetki yok!", show_alert=True); return
        # Şu anki bekleyen haberi atla, sonrakini göster
        hid  = context.bot_data.get("bekleyen_haber_id")
        hurl = context.bot_data.get("bekleyen_haber_url")
        if hid:  posted_news.add(hid)   # bu oturumda atla
        if hurl: posted_news.add(hurl)
        await q.message.edit_text("📰 Sonraki haber yükleniyor... ⏳")
        haberler = await fetch_crypto_news()
        yeni = [h for h in haberler if h["id"] not in posted_news and h["url"] not in posted_news]
        if not yeni:
            await q.message.edit_text("ℹ️ Başka yeni haber kalmadı.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 Admin", callback_data="menu_admin")
                                      ]]))
            return
        h  = yeni[0]
        ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
        text = haber_mesaj_formatla(h, ai, son_dk=ai.get("son_dk", False))
        context.bot_data["bekleyen_haber_text"] = text
        context.bot_data["bekleyen_haber_id"]   = h["id"]
        context.bot_data["bekleyen_haber_url"]  = h["url"]
        onizleme = "👁 *HABER ÖNİZLEME*\n━━━━━━━━━━━━━━━━━━━━\nGruba gönderilecek haber:\n\n" + text
        await q.message.edit_text(onizleme, parse_mode="Markdown",
                                  disable_web_page_preview=True,
                                  reply_markup=InlineKeyboardMarkup([
                                      [
                                          InlineKeyboardButton("✅ Gruba Gönder", callback_data="haber_onayla"),
                                          InlineKeyboardButton("❌ İptal",        callback_data="haber_iptal"),
                                      ],
                                      [InlineKeyboardButton("⏭ Sonraki Haber",   callback_data="haber_sonraki")],
                                  ]))

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
# OTOMATİK HABER + SON DAKİKA ALGILAMA
# ══════════════════════════════════════════════════════════════
async def auto_haber_job(context: ContextTypes.DEFAULT_TYPE):
    """Düzenli aralıklarla 1 haber paylaşır."""
    if GROUP_ID == 0 or not OPENAI_KEY:
        return
    if not haber_ayarlari.get("aktif", True):
        return
    haberler = await fetch_crypto_news()
    # posted_news URL bazlı da kontrol et (aynı haberin farklı id ile gelmesi durumu)
    yeni = [h for h in haberler if h["id"] not in posted_news and h["url"] not in posted_news]
    if not yeni:
        log.info("auto_haber_job: yeni haber yok")
        return
    # Sadece 1 haber gönder
    h = yeni[0]
    ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
    text = haber_mesaj_formatla(h, ai, son_dk=False)
    try:
        await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                       disable_web_page_preview=True)
        posted_news.add(h["id"])
        posted_news.add(h["url"])  # URL'yi de ekle
        log.info(f"Oto haber paylaşıldı: {h['baslik'][:60]}")
    except Exception as e:
        log.warning(f"Oto haber hatasi: {e}")


async def son_dk_haber_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Her 10 dakikada bir son dakika haberlerini kontrol eder.
    Son N dakika içinde yayınlanmış ve AI'ın son_dk=True dediği haberleri anında paylaşır.
    """
    global son_dk_kontrol
    if GROUP_ID == 0 or not OPENAI_KEY:
        return
    if not haber_ayarlari.get("son_dk_aktif", True):
        return

    esik_dk = haber_ayarlari.get("son_dk_esik", 15)
    su_an = datetime.utcnow()
    haberler = await fetch_crypto_news()

    for h in haberler:
        # Daha önce paylaşıldıysa atla (id VE url bazlı kontrol)
        if h["id"] in posted_news or h["url"] in posted_news:
            continue
        # Haberın zamanı son kontrol periyodundan daha yeni mi?
        try:
            haber_yasi_dk = (su_an - h["zaman"]).total_seconds() / 60
        except Exception:
            continue
        if haber_yasi_dk > esik_dk:
            continue

        # AI ile son dakika kontrolü
        ai = await openai_ozet(h.get("icerik", h.get("baslik", "")), h.get("baslik", ""))
        if not ai.get("son_dk", False):
            posted_news.add(h["id"])
            posted_news.add(h["url"])  # Son dk değil, kaydet ama paylaşma
            continue

        # SON DAKİKA — hemen paylaş!
        text = haber_mesaj_formatla(h, ai, son_dk=True)
        try:
            await context.bot.send_message(GROUP_ID, text, parse_mode="Markdown",
                                           disable_web_page_preview=True)
            posted_news.add(h["id"])
            posted_news.add(h["url"])  # URL'yi de kaydet
            log.info(f"Son dakika haberi paylaşıldı: {h['baslik'][:60]}")
            await asyncio.sleep(2)
        except Exception as e:
            log.warning(f"Son dk haber gonderilemedi: {e}")

    son_dk_kontrol = su_an


# ══════════════════════════════════════════════════════════════
# ADMİN — /haberayar  (haber sistemi ayarları)
# ══════════════════════════════════════════════════════════════
async def cmd_haber_ayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /haberayar          — Mevcut ayarları göster
    /haberayar ac       — Otomatik haberi aç
    /haberayar kapat    — Otomatik haberi kapat
    /haberayar adet 3   — Her seferinde 3 haber
    /haberayar sure 3   — 3 saatte bir paylaş
    /haberayar sondk ac — Son dakika algılamayı aç
    /haberayar sondk kapat
    /haberayar tag @KanalAdi
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komut sadece adminlere açıktır.")
        return

    args = context.args

    if not args:
        # Ayarları göster
        durum     = "✅ Açık" if haber_ayarlari["aktif"] else "❌ Kapalı"
        son_dk_d  = "✅ Açık" if haber_ayarlari["son_dk_aktif"] else "❌ Kapalı"
        text = (
            "⚙️ *Haber Sistemi Ayarları*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📰 Otomatik Haber: {durum}\n"
            f"⏱ Paylaşım Sıklığı: Her *{haber_ayarlari['interval_saat']}* saatte bir\n"
            f"📦 Haber Adedi: *{haber_ayarlari['adet']}* haber/seferinde\n"
            f"🚨 Son Dakika Algılama: {son_dk_d}\n"
            f"⏰ Son Dk Eşiği: *{haber_ayarlari['son_dk_esik']}* dakika içindeki haberler\n"
            f"🤖 Kanal Etiketi: {haber_ayarlari['kanal_tag']}\n\n"
            "*Komutlar:*\n"
            "`/haberayar ac` — Haberleri aç\n"
            "`/haberayar kapat` — Haberleri kapat\n"
            "`/haberayar adet 3` — 3 haber paylaş\n"
            "`/haberayar sure 6` — 6 saatte bir\n"
            "`/haberayar sondk ac` — Son dk aç\n"
            "`/haberayar sondk kapat`\n"
            "`/haberayar tag @KanalAdi`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    komut = args[0].lower()

    if komut == "ac":
        haber_ayarlari["aktif"] = True
        await update.message.reply_text("✅ Otomatik haber paylaşımı *açıldı*.", parse_mode="Markdown")

    elif komut == "kapat":
        haber_ayarlari["aktif"] = False
        await update.message.reply_text("❌ Otomatik haber paylaşımı *kapatıldı*.", parse_mode="Markdown")

    elif komut == "adet" and len(args) > 1:
        try:
            adet = int(args[1])
            assert 1 <= adet <= 10
            haber_ayarlari["adet"] = adet
            await update.message.reply_text(f"✅ Her seferinde *{adet}* haber paylaşılacak.", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("❌ Geçersiz. Örnek: `/haberayar adet 3`", parse_mode="Markdown")

    elif komut == "sure" and len(args) > 1:
        try:
            sure = int(args[1])
            assert sure in [1, 2, 3, 6, 12, 24]
            haber_ayarlari["interval_saat"] = sure
            await update.message.reply_text(
                f"✅ Haberler artık her *{sure}* saatte bir paylaşılacak.\n"
                f"⚠️ Bu değişiklik botu *yeniden başlatınca* geçerli olur.",
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Geçerli değerler: 1, 2, 3, 6, 12, 24", parse_mode="Markdown")

    elif komut == "sondk" and len(args) > 1:
        durum = args[1].lower()
        if durum == "ac":
            haber_ayarlari["son_dk_aktif"] = True
            await update.message.reply_text("✅ Son dakika algılama *açıldı*. (Her 10 dakikada kontrol)", parse_mode="Markdown")
        elif durum == "kapat":
            haber_ayarlari["son_dk_aktif"] = False
            await update.message.reply_text("❌ Son dakika algılama *kapatıldı*.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Kullanım: `/haberayar sondk ac` veya `/haberayar sondk kapat`", parse_mode="Markdown")

    elif komut == "tag" and len(args) > 1:
        haber_ayarlari["kanal_tag"] = args[1]
        await update.message.reply_text(f"✅ Kanal etiketi *{args[1]}* olarak ayarlandı.", parse_mode="Markdown")

    else:
        await update.message.reply_text("❌ Geçersiz komut. `/haberayar` yazarak mevcut ayarları gör.", parse_mode="Markdown")


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
        BotCommand("haberayar",    "Haber sistemi ayarları (admin)"),
        BotCommand("istatistik",   "Grup istatistikleri"),
        BotCommand("yardim",       "Yardım ve komutlar"),
    ])
    log.info("Komutlar ayarlandı.")


def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # Haber interval ayarlardan alınır
    haber_interval = haber_ayarlari.get("interval_saat", 6) * 3600
    app.job_queue.run_repeating(auto_haber_job, interval=haber_interval, first=300)
    app.job_queue.run_repeating(son_dk_haber_job, interval=600, first=120)  # Her 10 dk

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
    app.add_handler(CommandHandler("haberayar",       cmd_haber_ayar))
    app.add_handler(CommandHandler("duyuru",          cmd_duyuru))

    app.add_handler(CallbackQueryHandler(button_handler))

    log.info("KriptoDropTR Bot v3 Aktif 🚀")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
