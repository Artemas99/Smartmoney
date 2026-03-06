"""
FinTrack Telegram Bot - Pakai Gemini AI (GRATIS)
Scan struk foto & teks → simpan ke file JSON
"""
import os, re, json, logging, httpx
from datetime import datetime
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ── ENV VARS - set di Fly.io Secrets ─────────────────────────────────────────
BOT_TOKEN   = os.getenv("8623366248:AAEHWARidZ07Uulnt_h0_-o7fr5xkKkw4lw")
GEMINI_KEY  = os.getenv("AIzaSyBIJxNK-bYXSqn7lMSIA-hPUrEKaEYEGGY")
ALLOWED_IDS = set(os.getenv("1253881226").split(","))
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN belum di-set!")
if not GEMINI_KEY:
    raise ValueError("❌ GEMINI_KEY belum di-set!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt(n): return f"Rp {abs(n):,.0f}".replace(",", ".")
def is_allowed(chat_id): return not ALLOWED_IDS or str(chat_id) in ALLOWED_IDS
def today(): return datetime.now().strftime("%Y-%m-%d")

# ── Backend API ───────────────────────────────────────────────────────────────
async def send_to_backend(txs: list) -> bool:
    if not BACKEND_URL:
        log.warning("BACKEND_URL tidak di-set")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            payload = [{
                "date": tx.get("date", today()), "type": tx.get("type", "expense"),
                "category": tx.get("category", "Lainnya"), "amount": float(tx.get("amount", 0)),
                "desc": tx.get("desc", ""), "source": "telegram"
            } for tx in txs]
            resp = await client.post(f"{BACKEND_URL}/transactions", json=payload)
            resp.raise_for_status()
            return True
    except Exception as e:
        log.error(f"Backend error: {e}"); return False

async def get_report_today() -> dict:
    if not BACKEND_URL: return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return (await client.get(f"{BACKEND_URL}/report/today")).json()
    except: return {}

async def get_report_month() -> dict:
    if not BACKEND_URL: return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return (await client.get(f"{BACKEND_URL}/report/month")).json()
    except: return {}

# ── Gemini Parser ─────────────────────────────────────────────────────────────
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
        log.error(f"Gemini error: {e}"); return fallback_parse(text or "")

def fallback_parse(text):
    lower = text.lower()
    is_income = bool(re.search(r'gaji|terima|masuk|dapat|bayaran|honor', lower))
    nums = re.findall(r'[\d.,]+', text)
    amount = 0
    if nums:
        try:
            raw = nums[-1].replace('.','').replace(',','.')
            amount = float(raw)
            if amount < 1000: amount *= 1000
        except: pass
    cats = {
        'makan':'Makanan','minum':'Makanan','kopi':'Makanan','warung':'Makanan',
        'bensin':'Transport','ojek':'Transport','gojek':'Transport','grab':'Transport',
        'belanja':'Belanja','shopee':'Belanja','tokopedia':'Belanja',
        'listrik':'Tagihan','wifi':'Tagihan','pulsa':'Tagihan','token':'Tagihan',
        'netflix':'Hiburan','spotify':'Hiburan','game':'Hiburan',
        'obat':'Kesehatan','dokter':'Kesehatan','apotek':'Kesehatan',
        'gaji':'Gaji','salary':'Gaji','freelance':'Freelance','project':'Freelance',
    }
    category = next((v for k,v in cats.items() if k in lower), 'Lainnya')
    return {"type":"income" if is_income else "expense","amount":amount,"category":category,"desc":text[:80],"date":today()}

# ── Command Handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    await update.message.reply_text(
        "👋 *FinTrack Bot*\n\n"
        "📸 Kirim *foto struk* → otomatis diparse AI\n"
        "✍️ Contoh ketik:\n"
        "  • `Beli makan 35rb`\n"
        "  • `Gaji masuk 5 juta`\n"
        "  • `Bensin 50000`\n\n"
        "📊 /report — Laporan hari ini\n"
        "📈 /summary — Ringkasan bulan ini\n\n"
        "🌐 https://artemas99.github.io/Smartmoney",
        parse_mode="Markdown")

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    data = await get_report_today()
    inc, exp, bal, cnt = data.get("income",0), data.get("expense",0), data.get("balance",0), data.get("count",0)
    await update.message.reply_text(
        f"📊 *Laporan Hari Ini*\n━━━━━━━━━━━━━\n"
        f"⬆️ Pemasukan:   *{fmt(inc)}*\n"
        f"⬇️ Pengeluaran: *{fmt(exp)}*\n"
        f"💎 Saldo:       *{'+' if bal>=0 else '-'}{fmt(abs(bal))}*\n"
        f"📝 {cnt} transaksi", parse_mode="Markdown")

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    data = await get_report_month()
    inc, exp, bal, cnt = data.get("income",0), data.get("expense",0), data.get("balance",0), data.get("count",0)
    cats = data.get("top_categories", [])
    saving = round((inc-exp)/inc*100) if inc > 0 else 0
    cat_text = ""
    if cats:
        cat_text = "\n\n🗂 *Top Pengeluaran:*\n" + "".join(f"  {i}. {c['category']}: {fmt(c['total'])}\n" for i,c in enumerate(cats[:3],1))
    await update.message.reply_text(
        f"📈 *Bulan Ini*\n━━━━━━━━━━━━━\n"
        f"⬆️ Pemasukan:   *{fmt(inc)}*\n"
        f"⬇️ Pengeluaran: *{fmt(exp)}*\n"
        f"💎 Saldo:       *{'+' if bal>=0 else '-'}{fmt(abs(bal))}*\n"
        f"🎯 Tabungan:    *{saving}%*\n"
        f"📝 {cnt} transaksi{cat_text}", parse_mode="Markdown")

# ── Message Handlers ──────────────────────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    msg = await update.message.reply_text("🔍 Membaca struk...")
    try:
        photo = update.message.photo[-1]
        file  = await ctx.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        result = parse_with_gemini(text=update.message.caption, image_bytes=bytes(img_bytes))
        await show_confirmation(update, ctx, result, msg)
    except Exception as e:
        log.error(f"Photo error: {e}")
        await msg.edit_text("❌ Gagal baca struk. Coba kirim ulang.")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_chat.id): return
    if update.message.text.startswith("/"): return
    msg = await update.message.reply_text("🧠 Memproses...")
    try:
        result = parse_with_gemini(text=update.message.text)
        await show_confirmation(update, ctx, result, msg)
    except Exception as e:
        log.error(f"Text error: {e}")
        await msg.edit_text("❌ Tidak bisa memproses. Coba: `Beli makan 35rb`")

async def show_confirmation(update, ctx, result, msg):
    txs = result if isinstance(result, list) else [result]
    for tx in txs:
        is_inc = tx.get("type") == "income"
        text = (
            f"{'⬆️' if is_inc else '⬇️'} *Transaksi Terdeteksi*\n━━━━━━━━━━━━━\n"
            f"Tipe:     *{'Pemasukan' if is_inc else 'Pengeluaran'}*\n"
            f"Jumlah:   *{fmt(tx.get('amount',0))}*\n"
            f"Kategori: *{tx.get('category','?')}*\n"
            f"Tanggal:  *{tx.get('date','?')}*\n"
            f"Catatan:  {tx.get('desc','—')}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Simpan", callback_data=f"save:{json.dumps(tx,ensure_ascii=False)}"),
            InlineKeyboardButton("❌ Batal",  callback_data="cancel")
        ]])
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Dibatalkan."); return
    if query.data.startswith("save:"):
        tx = json.loads(query.data[5:])
        ok = await send_to_backend([tx])
        await query.edit_message_text(
            f"✅ *Tersimpan!*\n{fmt(tx.get('amount',0))} — {tx.get('category')} dicatat!\n\n🌐 https://artemas99.github.io/Smartmoney"
            if ok else
            f"⚠️ *Gagal kirim ke backend*\nPastikan BACKEND_URL sudah di-set di Fly.io Secrets.",
            parse_mode="Markdown")

def main():
    log.info("🤖 FinTrack Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_start))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    log.info("✅ Bot running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
