# KriptoDropTR Bot 🤖

Telegram grup karşılama ve airdrop takip botu.

---

## 🚀 Railway'de Kurulum

### 1. GitHub'a Yükle
```bash
git init
git add .
git commit -m "ilk yükleme"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADIN/REPO_ADIN.git
git push -u origin main
```

### 2. Railway Projesi Oluştur
1. [railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** seç
3. Repoyu bağla → otomatik deploy başlar

### 3. Environment Variable Ekle
Railway panelinde projeye tıkla → **Variables** sekmesi → **+ New Variable**:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | `BotFather'dan aldığın token` |

Değişkeni kaydedince Railway otomatik yeniden başlatır, bot aktif olur.

---

## 📋 Komutlar

### Herkes kullanabilir
| Komut | Açıklama |
|-------|----------|
| `/airdrops` | Aktif airdrop listesini göster |
| `/istatistik` | Katılım istatistikleri (günlük/haftalık/aylık) |
| `/yardim` | Tüm komutları listele |

### Admin komutları
| Komut | Açıklama |
|-------|----------|
| `/airdropekle İsim \| Ödül \| Bitiş \| Link` | Yeni airdrop ekle |
| `/airdropbitir <id>` | Airdropi sonlandır |
| `/airdropsil <id>` | Listeden tamamen sil |
| `/airdroptumu` | Aktif + bitmiş tüm airdropları gör |

**Airdrop ekleme örneği:**
```
/airdropekle Layer3 | 50 USDT | 31.12.2025 | https://layer3.xyz
```

---

## 📁 Dosya Yapısı
```
├── bot.py           # Ana bot kodu
├── requirements.txt # Python bağımlılıkları
├── Procfile         # Railway başlatma komutu
├── railway.toml     # Railway ayarları
├── .gitignore       # Git'e yüklenmeyecek dosyalar
└── README.md        # Bu dosya
```

---

## ⚠️ Not
Airdrop verileri ve istatistikler **RAM'de** tutulur. Bot yeniden başlarsa (Railway restart, deploy vs.) veriler sıfırlanır. Kalıcı depolama için Railway'e PostgreSQL eklentisi bağlanabilir.
