"""
FinTrack Telegram Bot - Pakai Gemini AI (GRATIS)
Scan struk foto & teks → simpan ke file JSON
"""

import os, re, json, logging
from datetime import datetime
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_KEY  = os.getenv("GEMINI_API_KEY", "")
ALLOWED_IDS = set(os.getenv("ALLOWED_CHAT_IDS", "").split(","))
DATA_FILE   = os.path.join(os.path.dirname(__file__), "data.json")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f: return json.load(f)
    return []

def save_tx(tx):
    data = load_data()
    tx["id"] = f"{datetime.now().timestamp():.6f}"
    tx["source"] = "telegram"
    data.append(tx)
    with open(DATA_FILE, "w") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    return tx

def fmt(n): return f"Rp {abs(n):,.0f}".replace(",", ".")
def is_allowed(chat_id): return not ALLOWED_IDS or str(chat_id) in ALLOWED_IDS
def today(): return datetime.now().strftime("%Y-%m-%d")

def parse_with_gemini(text=None, image_bytes=None):
    prompt = f"""Kamu asisten keuangan. Hari ini {today()}.
Parse transaksi dan kembalikan JSON saja tanpa teks lain.
Format: {{"type":"income/expense","amount":angka,"category":"Makanan/Transport/Belanja/Tagihan/Hiburan/Kesehatan/Pendidikan/Gaji/Freelance/Investasi/Lainnya","desc":"deskripsi","date":"YYYY-MM-DD"}}
Jika banyak item kembalikan array. Input: {text or 'lihat gambar'}"""
    try:
        if image_bytes:
            import PIL.Image, io
            img = PIL.Image.open(io.BytesIO(image_bytes))
            response = model.generate_content([prompt, img])
        else:
            response = model.generate_content(prompt)
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Gemini error: {e}")
        return fallback_parse(text or "")

def fallback_parse(text):
    lower = text.lower()
    is_income = bool(re.search(r'gaji|terima|masuk|dapat|bayaran|honor', lower))
    nums = re.findall(r'[\d.,]+', text)
    amount = 0
    if nums:
        raw = nums[-1].replace('.','').replace(',','.')
        amount = float(raw)
        if amount < 1000: amount *= 1000
    cats = {'makan':'Makanan','bensin':'Transport','ojek':'Transport','gojek':'Transport','grab':'Transport','belanja':'Belanja','listrik':'Tagihan','wifi':'Tagihan','netflix':'Hiburan','obat':'Kesehatan','dokter':'Kesehatan','gaji':'Gaji','freelance':'Freelance'}
    category = next((v for k,v in cats.items() if k in lower), 'Lainnya')
    return {"type":"income" if is_income else "expense","amount":amount,"category":category,"desc":text[:50],"date":today()}

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    await update.message.reply_text("👋 *FinTrack Bot*\n\n📸 Kirim foto struk → otomatis diparse\n✍️ Ketik: `Beli makan 35rb` atau `Gaji 5 juta`\n\n📊 /report — Hari ini\n📈 /summary — Bulan ini", parse_mode="Markdown")

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    data = [t for t in load_data() if t.get("date") == today()]
    inc = sum(t["amount"] for t in data if t["type"]=="income")
    exp = sum(t["amount"] for t in data if t["type"]=="expense")
    await update.message.reply_text(f"📊 *Laporan Hari Ini*\n━━━━━━━━━━━━━\n⬆️ Pemasukan: *{fmt(inc)}*\n⬇️ Pengeluaran: *{fmt(exp)}*\n💎 Saldo: *{fmt(inc-exp)}*\n📝 {len(data)} transaksi", parse_mode="Markdown")

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    prefix = datetime.now().strftime("%Y-%m")
    data = [t for t in load_data() if t.get("date","").startswith(prefix)]
    inc = sum(t["amount"] for t in data if t["type"]=="income")
    exp = sum(t["amount"] for t in data if t["type"]=="expense")
    saving = round((inc-exp)/inc*100) if inc > 0 else 0
    await update.message.reply_text(f"📈 *Bulan Ini*\n━━━━━━━━━━━━━\n⬆️ Pemasukan: *{fmt(inc)}*\n⬇️ Pengeluaran: *{fmt(exp)}*\n💎 Saldo: *{fmt(inc-exp)}*\n🎯 Tabungan: *{saving}%*", parse_mode="Markdown")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    msg = await update.message.reply_text("🔍 Membaca struk...")
    try:
        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        result = parse_with_gemini(text=update.message.caption, image_bytes=bytes(img_bytes))
        await show_confirmation(update, ctx, result, msg)
    except Exception as e:
        await msg.edit_text(f"❌ Gagal baca struk. Coba kirim ulang.")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    if update.message.text.startswith("/"): return
    msg = await update.message.reply_text("🧠 Memproses...")
    try:
        result = parse_with_gemini(text=update.message.text)
        await show_confirmation(update, ctx, result, msg)
    except:
        await msg.edit_text("❌ Tidak bisa memproses.")

async def show_confirmation(update, ctx, result, msg):
    txs = result if isinstance(result, list) else [result]
    for tx in txs:
        icon = "⬆️" if tx.get("type")=="income" else "⬇️"
        text = f"{icon} *Terdeteksi*\n━━━━━━━━━━━━━\nTipe: *{'Pemasukan' if tx.get('type')=='income' else 'Pengeluaran'}*\nJumlah: *{fmt(tx.get('amount',0))}*\nKategori: *{tx.get('category','?')}*\nTanggal: *{tx.get('date','?')}*\nCatatan: {tx.get('desc','—')}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Simpan", callback_data=f"save:{json.dumps(tx)}"), InlineKeyboardButton("❌ Batal", callback_data="cancel")]])
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Dibatalkan.")
    elif query.data.startswith("save:"):
        tx = json.loads(query.data[5:])
        save_tx(tx)
        await query.edit_message_text(f"✅ *Tersimpan!*\n{fmt(tx.get('amount',0))} ({tx.get('category')}) dicatat!\n\nLihat: https://artemas99.github.io/Webkeuangan", parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    log.info("🤖 Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
