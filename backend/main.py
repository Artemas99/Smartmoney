"""
FinTrack Backend API
Menyimpan transaksi, serve ke frontend, integrasi Google Sheets
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
import json, os, gspread
from google.oauth2.service_account import Credentials

app = FastAPI(title="FinTrack API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Data store (file-based, ganti ke DB di production) ────────────────────────
DATA_FILE = "data/transactions.json"
os.makedirs("data", exist_ok=True)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def save_data(txs):
    with open(DATA_FILE, "w") as f:
        json.dump(txs, f, indent=2, ensure_ascii=False)

# ── Models ────────────────────────────────────────────────────────────────────
class Transaction(BaseModel):
    date: str
    type: str           # income / expense
    category: str
    amount: float
    desc: Optional[str] = ""
    source: Optional[str] = "manual"  # manual / telegram / ai

class TransactionOut(Transaction):
    id: str

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "FinTrack API running ✅"}

@app.post("/transactions")
def add_transactions(txs: List[Transaction]):
    data = load_data()
    new_items = []
    for tx in txs:
        item = tx.dict()
        item["id"] = f"{datetime.now().timestamp():.6f}"
        data.append(item)
        new_items.append(item)
    save_data(data)
    sync_to_sheets(new_items)
    return {"added": len(new_items), "items": new_items}

@app.get("/transactions")
def get_transactions(since: Optional[str] = None, limit: int = 500):
    data = load_data()
    if since:
        data = [t for t in data if t.get("date", "") >= since]
    data.sort(key=lambda x: x.get("date",""), reverse=True)
    return data[:limit]

@app.get("/report/today")
def report_today():
    today = date.today().isoformat()
    data = [t for t in load_data() if t.get("date") == today]
    income  = sum(t["amount"] for t in data if t["type"] == "income")
    expense = sum(t["amount"] for t in data if t["type"] == "expense")
    return {"date": today, "income": income, "expense": expense, "balance": income-expense, "count": len(data)}

@app.get("/report/month")
def report_month(year: int = None, month: int = None):
    now = datetime.now()
    y, m = year or now.year, month or now.month
    prefix = f"{y}-{m:02d}"
    data = [t for t in load_data() if t.get("date","").startswith(prefix)]
    income  = sum(t["amount"] for t in data if t["type"] == "income")
    expense = sum(t["amount"] for t in data if t["type"] == "expense")
    cats = {}
    for t in data:
        if t["type"] == "expense":
            cats[t["category"]] = cats.get(t["category"],0) + t["amount"]
    top_cats = sorted([{"category":k,"total":v} for k,v in cats.items()], key=lambda x:-x["total"])
    return {"year":y,"month":m,"income":income,"expense":expense,"balance":income-expense,"count":len(data),"top_categories":top_cats[:5]}

@app.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: str):
    data = load_data()
    data = [t for t in data if t.get("id") != tx_id]
    save_data(data)
    return {"deleted": tx_id}

# ── Google Sheets Sync ─────────────────────────────────────────────────────────
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "google-creds.json")

def sync_to_sheets(txs: list):
    if not SHEET_ID or not os.path.exists(CREDS_FILE):
        return
    try:
        creds = Credentials.from_service_account_file(
            CREDS_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SHEET_ID).sheet1
        # Add header if empty
        if ws.row_count == 0 or not ws.cell(1,1).value:
            ws.append_row(["ID","Tanggal","Tipe","Kategori","Jumlah","Keterangan","Sumber"])
        for tx in txs:
            ws.append_row([
                tx.get("id",""),
                tx.get("date",""),
                tx.get("type",""),
                tx.get("category",""),
                tx.get("amount",0),
                tx.get("desc",""),
                tx.get("source",""),
            ])
    except Exception as e:
        print(f"Sheets sync error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
