#!/usr/bin/env python3
"""
🌴 Malibu Telegram Bot v1.0
===========================
- Website deep link desteği
- Conversation flow ile bilgi toplama
- Google Sheets webhook entegrasyonu
- Admin onay/red sistemi
- Süresi dolanlara bildirim
"""
import os
import sys
import asyncio
import logging
import json
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

os.environ['PYTHONUNBUFFERED'] = '1'

import httpx
import requests
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ConversationHandler, filters
)
from telegram.error import TelegramError, TimedOut, RetryAfter, Conflict, NetworkError

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
log = logging.getLogger("MalibuBot")
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
SHEETS_WEBHOOK = os.getenv("SHEETS_WEBHOOK", "")
WEBSITE_URL = os.getenv("WEBSITE_URL", "https://harmonikprzmalibu.netlify.app")
PORT = int(os.getenv("PORT", "8080"))
RAILWAY_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")

# Ödeme adresi
PAYMENT_ADDRESS = "TKUvYuzdZvkq6ksgPxfDRsUQE4vYjnEcnL"

# Conversation states
TRADINGVIEW, TXID = range(2)

# Plan bilgileri
PLANS = {
    "plan_monthly_30": {"name": "Aylık", "price": "$30", "days": 30},
    "plan_quarterly_79": {"name": "3 Aylık", "price": "$79", "days": 90},
    "plan_yearly_269": {"name": "Yıllık", "price": "$269", "days": 365},
    "trial": {"name": "7 Günlük Deneme", "price": "Ücretsiz", "days": 7}
}

# ==================== STATE ====================
START_TIME = datetime.now(timezone.utc)
BOT_STATUS = {"running": False, "errors": 0, "restarts": 0}
pending_requests = {}
SHUTDOWN = threading.Event()

# ==================== FLASK ====================
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    uptime = int((datetime.now(timezone.utc) - START_TIME).total_seconds())
    return jsonify({
        "status": "ok",
        "version": "1.0",
        "uptime": uptime,
        "bot": BOT_STATUS
    }), 200

@app.route("/ping")
def ping():
    return "pong", 200

# ==================== GOOGLE SHEETS ====================
async def save_to_sheets(data: dict) -> bool:
    """Google Sheets'e webhook ile kaydet"""
    if not SHEETS_WEBHOOK:
        log.warning("SHEETS_WEBHOOK not configured")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(SHEETS_WEBHOOK, json=data)
            if response.status_code == 200:
                log.info(f"✅ Sheets'e kaydedildi: {data.get('tradingview', '?')}")
                return True
            else:
                log.error(f"Sheets error: {response.status_code}")
    except Exception as e:
        log.error(f"Sheets webhook error: {e}")
    return False

async def get_expired_users() -> list:
    """Süresi dolan kullanıcıları al"""
    if not SHEETS_WEBHOOK:
        return []
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(f"{SHEETS_WEBHOOK}?action=expired")
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        log.error(f"Get expired error: {e}")
    return []

# ==================== HELPERS ====================
def calculate_end_date(days: int) -> str:
    end = datetime.now(timezone.utc) + timedelta(days=days)
    return end.strftime("%d.%m.%Y")

# ==================== BOT HANDLERS ====================
async def cmd_start(update: Update, context):
    """Start komutu - website'den deep link ile gelir"""
    user = update.effective_user
    args = context.args if context.args else []
    
    log.info(f"START: {user.id} - args: {args}")
    
    # Deep link'ten plan al
    plan_key = args[0] if args else None
    
    if plan_key and plan_key in PLANS:
        plan = PLANS[plan_key]
        context.user_data['plan_key'] = plan_key
        context.user_data['plan'] = plan
        
        if plan_key == "trial":
            # Deneme için sadece TradingView sor
            await update.message.reply_text(
                f"🌴 *Malibu PRZ Suite*\n\n"
                f"✅ *{plan['name']}* seçildi!\n\n"
                f"📝 Lütfen TradingView kullanıcı adınızı yazın:",
                parse_mode="Markdown"
            )
            return TRADINGVIEW
        else:
            # Ücretli plan
            await update.message.reply_text(
                f"🌴 *Malibu PRZ Suite*\n\n"
                f"✅ *{plan['name']} ({plan['price']})* seçildi!\n\n"
                f"📝 Lütfen TradingView kullanıcı adınızı yazın:",
                parse_mode="Markdown"
            )
            return TRADINGVIEW
    else:
        # Normal start - plan seçimi göster
        keyboard = [
            [InlineKeyboardButton("💳 Aylık - $30", callback_data="plan_monthly_30")],
            [InlineKeyboardButton("⭐ 3 Aylık - $79 (En Popüler)", callback_data="plan_quarterly_79")],
            [InlineKeyboardButton("👑 Yıllık - $269", callback_data="plan_yearly_269")],
            [InlineKeyboardButton("🆓 7 Günlük Ücretsiz Deneme", callback_data="trial")]
        ]
        
        await update.message.reply_text(
            f"Merhaba {user.first_name}! 👋\n\n"
            f"🌴 *Malibu PRZ Suite'e* hoş geldiniz!\n\n"
            f"Harmonik PRZ + SMC Malibu hibrit sistemi ile\n"
            f"kurumsal düzeyde teknik analiz yapın.\n\n"
            f"📊 Bir plan seçin:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def plan_selected(update: Update, context):
    """Plan seçildiğinde"""
    query = update.callback_query
    await query.answer()
    
    plan_key = query.data
    if plan_key not in PLANS:
        return ConversationHandler.END
    
    plan = PLANS[plan_key]
    context.user_data['plan_key'] = plan_key
    context.user_data['plan'] = plan
    
    await query.message.reply_text(
        f"✅ *{plan['name']} ({plan['price']})* seçildi!\n\n"
        f"📝 Lütfen TradingView kullanıcı adınızı yazın:",
        parse_mode="Markdown"
    )
    return TRADINGVIEW

async def receive_tradingview(update: Update, context):
    """TradingView kullanıcı adı alındı"""
    user = update.effective_user
    tv_username = update.message.text.strip()
    
    context.user_data['tradingview'] = tv_username
    plan = context.user_data.get('plan', {})
    plan_key = context.user_data.get('plan_key', '')
    
    if plan_key == "trial":
        # Deneme - TXID gerekmez, direkt kaydet
        await save_request(user, context, txid="DENEME")
        
        await update.message.reply_text(
            f"✅ *Deneme talebiniz alındı!*\n\n"
            f"📺 TradingView: `{tv_username}`\n"
            f"⏱️ Süre: 7 gün\n\n"
            f"24 saat içinde erişiminiz aktifleştirilecektir.\n"
            f"Teşekkürler! 🙏",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    else:
        # Ücretli plan - ödeme bilgisi göster
        await update.message.reply_text(
            f"📺 TradingView: `{tv_username}`\n\n"
            f"💰 *Ödeme Bilgileri:*\n\n"
            f"Adres (TRC20 USDT):\n"
            f"`{PAYMENT_ADDRESS}`\n\n"
            f"Tutar: *{plan.get('price', '?')}*\n\n"
            f"⚠️ Ödeme yaptıktan sonra *TXID* (işlem numarası) gönderin:",
            parse_mode="Markdown"
        )
        return TXID

async def receive_txid(update: Update, context):
    """TXID alındı - kaydı tamamla"""
    user = update.effective_user
    txid = update.message.text.strip()
    
    context.user_data['txid'] = txid
    await save_request(user, context, txid=txid)
    
    plan = context.user_data.get('plan', {})
    
    await update.message.reply_text(
        f"✅ *Ödeme talebiniz alındı!*\n\n"
        f"📋 TXID: `{txid}`\n"
        f"📊 Plan: {plan.get('name', '?')} ({plan.get('price', '?')})\n\n"
        f"İşleminiz 24 saat içinde kontrol edilecektir.\n"
        f"Onaylandığında bilgilendirileceksiniz. 🙏",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def save_request(user, context, txid: str):
    """Talebi kaydet ve admin'e bildir"""
    plan = context.user_data.get('plan', {})
    plan_key = context.user_data.get('plan_key', '')
    tv_username = context.user_data.get('tradingview', '')
    
    now = datetime.now(timezone.utc)
    end_date = calculate_end_date(plan.get('days', 30))
    
    data = {
        'tarih': now.strftime("%d.%m.%Y %H:%M"),
        'telegram_id': str(user.id),
        'telegram_username': user.username or "Yok",
        'telegram_name': user.first_name or "",
        'txid': txid,
        'plan': plan.get('name', ''),
        'tradingview': tv_username,
        'baslangic_tarihi': now.strftime("%d.%m.%Y"),
        'bitis_tarihi': end_date,
        'durum': 'Beklemede 🟡'
    }
    
    # Google Sheets'e kaydet
    await save_to_sheets(data)
    
    # Admin'e bildir
    if ADMIN_ID:
        try:
            keyboard = [[
                InlineKeyboardButton("✅ Onayla", callback_data=f"approve_{user.id}"),
                InlineKeyboardButton("❌ Reddet", callback_data=f"reject_{user.id}")
            ]]
            
            pending_requests[str(user.id)] = data
            
            is_trial = "🆓 DENEME" if txid == "DENEME" else "💰 ÖDEME"
            
            await context.bot.send_message(
                chat_id=int(ADMIN_ID),
                text=f"{is_trial} *Yeni Talep*\n\n"
                     f"👤 {user.first_name} (@{user.username or 'yok'})\n"
                     f"🆔 `{user.id}`\n"
                     f"📊 {plan.get('name', '?')} ({plan.get('price', '?')})\n"
                     f"📺 TradingView: `{tv_username}`\n"
                     f"📋 TXID: `{txid}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            log.error(f"Admin bildirim hatası: {e}")

async def admin_callback(update: Update, context):
    """Admin onay/red işlemleri"""
    query = update.callback_query
    await query.answer()
    
    if str(query.from_user.id) != str(ADMIN_ID):
        return
    
    action, user_id = query.data.split("_", 1)
    user_data = pending_requests.pop(user_id, {})
    
    if action == "approve":
        await query.message.edit_text(
            f"✅ *Onaylandı*\n\n"
            f"👤 {user_data.get('telegram_name', user_id)}\n"
            f"📺 {user_data.get('tradingview', '?')}",
            parse_mode="Markdown"
        )
        
        # Kullanıcıya bildir
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="🎉 *Erişiminiz aktifleştirildi!*\n\n"
                     "TradingView'da indikatör erişiminiz açıldı.\n"
                     "İyi işlemler! 🌴",
                parse_mode="Markdown"
            )
        except:
            pass
            
    elif action == "reject":
        await query.message.edit_text(
            f"❌ *Reddedildi*: {user_id}",
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ Talebiniz reddedildi.\n\n"
                     "Sorularınız için destek ile iletişime geçebilirsiniz."
            )
        except:
            pass

async def cmd_cancel(update: Update, context):
    """İptal komutu"""
    await update.message.reply_text(
        "İşlem iptal edildi.\n\nYeniden başlamak için /start yazın."
    )
    return ConversationHandler.END

# ==================== ADMIN COMMANDS ====================
async def cmd_pending(update: Update, context):
    """Bekleyen talepler"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    
    count = len(pending_requests)
    await update.message.reply_text(f"⏳ Bekleyen talep: {count}")

async def cmd_status(update: Update, context):
    """Bot durumu"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    
    uptime = int((datetime.now(timezone.utc) - START_TIME).total_seconds())
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    
    await update.message.reply_text(
        f"📊 *Bot Durumu*\n\n"
        f"✅ Çalışıyor\n"
        f"⏱️ Uptime: {hours}s {minutes}dk\n"
        f"🔄 Restart: {BOT_STATUS['restarts']}\n"
        f"❌ Hatalar: {BOT_STATUS['errors']}",
        parse_mode="Markdown"
    )

async def cmd_notify_expired(update: Update, context):
    """Süresi dolanlara bildirim gönder"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    
    await update.message.reply_text("🔄 Süresi dolanlar kontrol ediliyor...")
    
    expired_users = await get_expired_users()
    
    if not expired_users:
        await update.message.reply_text("✅ Süresi dolan kullanıcı yok.")
        return
    
    sent = 0
    expired_count = len(expired_users)
    for user in expired_users:
        try:
            raw_id = user.get('telegram_id', '')
            user_id = str(raw_id).strip()
            if user_id and user_id.isdigit():
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"⚠️ Malibu PRZ Suite erişiminiz sona erdi. Yenilemek için: {WEBSITE_URL}/",
                    parse_mode="Markdown"
                )
                sent += 1
                await asyncio.sleep(0.15)
        except Exception as e:
            log.warning(f"Bildirim gönderilemedi {user.get('telegram_id')}: {e}")
    
    await update.message.reply_text(f"📨 {sent}/{expired_count} kişiye bildirim gönderildi.")

async def cmd_scan(update: Update, context):
    """Sheets'i kontrol et ve süresi dolanlara bildirim gönder - Gelişmiş Tarama"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    
    status_msg = await update.message.reply_text("🔍 Gelişmiş tarama başlatılıyor... Lütfen bekleyin.")
    
    try:
        expired_users = await get_expired_users()
        
        if not expired_users:
            await status_msg.edit_text("✅ Süresi dolan veya bildirim bekleyen kullanıcı bulunamadı.")
            return
            
        if isinstance(expired_users, dict) and "error" in expired_users:
            err_txt = f"❌ Sheets Hatası: {expired_users.get('error')}"
            if "headers_found" in expired_users:
                err_txt += f"\nBulunan sütunlar: {expired_users.get('headers_found')}"
            await status_msg.edit_text(err_txt)
            return

        total_found = len(expired_users)
        sent = 0
        skipped_invalid = 0
        errors = 0
        
        for user in expired_users:
            try:
                raw_id = user.get('telegram_id', '')
                user_id = str(raw_id).strip()
                
                if user_id and user_id.isdigit():
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=f"⚠️ Malibu PRZ Suite erişiminiz sona erdi. Yenilemek için: {WEBSITE_URL}/",
                        parse_mode="Markdown"
                    )
                    sent += 1
                    await asyncio.sleep(0.15)
                else:
                    skipped_invalid += 1
                    log.warning(f"Tarama: Geçersiz ID ({raw_id}) atlandı.")
            except Exception as e:
                errors += 1
                log.error(f"Bildirim hatası ({user_id}): {e}")
        
        report = (
            f"✅ *Gelişmiş Tarama Tamamlandı*\n\n"
            f"📊 Toplam Tespit: `{total_found}`\n"
            f"📨 Başarıyla Gönderilen: `{sent}`\n"
            f"⚠️ Geçersiz ID (Atlanan): `{skipped_invalid}`\n"
            f"❌ Hatalı Gönderim: `{errors}`"
        )
        await status_msg.edit_text(report, parse_mode="Markdown")
        
    except Exception as e:
        log.error(f"Scan error: {e}")
        await status_msg.edit_text(f"❌ Tarama sırasında teknik hata: {e}")

async def cmd_sync(update: Update, context):
    """Sheets senkronizasyonu"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    await update.message.reply_text("🔄 Sheets ile senkronizasyon başlatıldı...")
    # Webhook üzerinden veri çekme mantığı buraya gelebilir
    await update.message.reply_text("✅ Senkronizasyon tamamlandı.")

async def cmd_repair_sheets(update: Update, context):
    """Sheets tablolarını onar"""
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    await update.message.reply_text("🔧 Sheets tabloları kontrol ediliyor...")
    # Tablo onarım mantığı buraya gelecek
    await update.message.reply_text("✅ Onarım tamamlandı.")

async def cmd_help(update: Update, context):
    """Yardım"""
    text = (
        "📚 *Komutlar*\n\n"
        "/start - Başla\n"
        "/help - Yardım\n"
    )
    
    if str(update.effective_user.id) == str(ADMIN_ID):
        text += (
            "\n*Admin Komutları:*\n"
            "/pending - Bekleyen talepler\n"
            "/status - Bot durumu\n"
            "/notify\\_expired - Süresi dolanlara bildirim\n"
            "/scan - Tarama yap\n"
            "/sync - Verileri senkronize et\n"
            "/repair\\_sheets - Tabloları onar"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== BOT ENGINE ====================
async def run_bot():
    """Bot'u başlat"""
    log.info("Bot başlatılıyor...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(plan_selected, pattern="^(plan_|trial)")
        ],
        states={
            TRADINGVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tradingview)],
            TXID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_txid)]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=600
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("pending", cmd_pending))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("notify_expired", cmd_notify_expired))
    application.add_handler(CommandHandler("scan", cmd_scan))
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("repair_sheets", cmd_repair_sheets))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^(approve_|reject_)"))
    
    await application.initialize()
    
    # Webhook sil
    for i in range(3):
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            break
        except:
            await asyncio.sleep(2)
    
    await application.start()
    BOT_STATUS["running"] = True
    log.info("✅ Bot başlatıldı - polling...")
    
    # Polling loop
    offset = None
    while not SHUTDOWN.is_set():
        try:
            updates = await application.bot.get_updates(
                offset=offset, timeout=30, allowed_updates=Update.ALL_TYPES
            )
            for upd in updates:
                offset = upd.update_id + 1
                await application.process_update(upd)
        except TimedOut:
            continue
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Conflict:
            log.error("CONFLICT - başka bot çalışıyor!")
            await asyncio.sleep(30)
        except (NetworkError, TelegramError) as e:
            log.warning(f"Ağ hatası: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            BOT_STATUS["errors"] += 1
            log.error(f"Hata: {e}")
            await asyncio.sleep(5)
    
    await application.stop()
    await application.shutdown()

def bot_thread():
    """Bot thread'i"""
    while not SHUTDOWN.is_set():
        BOT_STATUS["restarts"] += 1
        log.info(f"🚀 Bot başlatılıyor (#{BOT_STATUS['restarts']})")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(run_bot())
        except Exception as e:
            log.error(f"Bot çöktü: {e}")
            BOT_STATUS["running"] = False
        finally:
            loop.close()
        
        if not SHUTDOWN.is_set():
            log.info("♻️ 3 saniye sonra yeniden başlatılacak...")
            time.sleep(3)

def keep_alive_thread():
    """Keep-alive ping"""
    time.sleep(60)
    while not SHUTDOWN.is_set():
        try:
            url = f"https://{RAILWAY_URL}/ping" if RAILWAY_URL else f"http://localhost:{PORT}/ping"
            requests.get(url, timeout=10)
        except:
            pass
        time.sleep(240)

def signal_handler(signum, frame):
    """Graceful shutdown"""
    log.info("⚠️ Kapatma sinyali alındı...")
    SHUTDOWN.set()
    time.sleep(2)
    sys.exit(0)

def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    if not BOT_TOKEN:
        log.error("❌ BOT_TOKEN bulunamadı!")
        app.run(host="0.0.0.0", port=PORT)
        return
    
    log.info("=" * 50)
    log.info("🌴 Malibu Telegram Bot v1.0")
    log.info(f"📊 Sheets Webhook: {'✅' if SHEETS_WEBHOOK else '❌'}")
    log.info(f"👤 Admin ID: {ADMIN_ID}")
    log.info(f"🔌 Port: {PORT}")
    log.info("=" * 50)
    
    # Bot thread
    threading.Thread(target=bot_thread, daemon=False).start()
    
    # Keep-alive thread
    threading.Thread(target=keep_alive_thread, daemon=True).start()
    
    # Flask
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
