import os
import json
import aiohttp
from datetime import datetime

STOCK_CACHE_FILE = "stock_cache.json"

def load_cached_stock() -> dict:
    if not os.path.exists(STOCK_CACHE_FILE):
        default = {"boost_1m": 0, "boost_3m": 0}
        with open(STOCK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=4)
        return default
    try:
        with open(STOCK_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"boost_1m": 0, "boost_3m": 0}

def save_cached_stock(stock_data: dict):
    with open(STOCK_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(stock_data, f, ensure_ascii=False, indent=4)

async def send_stock_webhook(webhook_url: str, content: str, title: str, description: str, color: int = 0x57F287):
    """
    ส่ง Webhook พร้อม content (สำหรับแท็กยศ) และ Embed
    """
    if not webhook_url:
        return
    
    payload = {
        "content": content,  # แท็กยศจะอยู่ตรงนี้ เช่น <@&ROLE_ID>
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {
                    "text": "PL SHOP - STOCK NOTIFIER"
                }
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status not in (200, 204):
                    print(f"[Stock Webhook Warn]: Status {resp.status}")
        except Exception as e:
            print(f"[Stock Webhook Error]: {e}")

async def process_stock_update(current_stock: dict, webhook_url: str, notify_role_id: str = None):
    """
    เปรียบเทียบสต็อกล่าสุดกับแคชใน JSON
    แจ้ง Webhook พร้อมแท็กยศ เฉพาะเมื่อจำนวนสต็อก 'เพิ่มขึ้น' จากเดิม
    """
    cached = load_cached_stock()
    
    c_1m = current_stock.get("boost_1m", 0)
    c_3m = current_stock.get("boost_3m", 0)
    
    old_1m = cached.get("boost_1m", 0)
    old_3m = cached.get("boost_3m", 0)

    increased_items = []

    # 1. ตรวจสอบสต็อก 1 เดือน
    if c_1m > old_1m:
        diff_1m = c_1m - old_1m
        increased_items.append(f"🌸 **บูสต์ 1 เดือน**: เติมเข้า `+{diff_1m}` เม็ด ➜ สต็อกคงเหลือ `{c_1m}` เม็ด")

    # 2. ตรวจสอบสต็อก 3 เดือน
    if c_3m > old_3m:
        diff_3m = c_3m - old_3m
        increased_items.append(f"🌸 **บูสต์ 3 เดือน**: เติมเข้า `+{diff_3m}` เม็ด ➜ สต็อกคงเหลือ `{c_3m}` เม็ด")

    # บันทึกแคชค่าล่าสุดเสมอ (ทั้งกรณีเพิ่มขึ้น หรือกรณีมีคนซื้อแล้วลดลง)
    save_cached_stock({"boost_1m": c_1m, "boost_3m": c_3m})

    # 3. ยิง Webhook เฉพาะเมื่อสต็อกมีการเพิ่มขึ้น
    if increased_items and webhook_url:
        # จัดรูปแบบข้อความ Mention
        mention_content = ""
        if notify_role_id:
            role_id_clean = str(notify_role_id).strip()
            if role_id_clean in ("@everyone", "@here"):
                mention_content = role_id_clean
            elif role_id_clean.isdigit():
                mention_content = f"<@&{role_id_clean}>"
            else:
                mention_content = role_id_clean

        desc = "\n".join(increased_items)
        await send_stock_webhook(
            webhook_url=webhook_url,
            content=mention_content,
            title="<a:245_boost:1175394139504910336> สต็อกบูสต์เติมแล้ว! (RESTOCK)",
            description=f"ระบบตรวจพบสต็อกเพิ่มเข้าสู่ระบบเรียบร้อยแล้ว:\n\n{desc}\n\n*รีบสั่งซื้อก่อนสต็อกจะหมดนะครับ!* \n สั่งซื้อได้ที่ <a:botsever16:1184852397982502922> https://discord.com/channels/1170666107556864051/1551859567107903488 !!"
        )