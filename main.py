import os
import json
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import config
from services.stock_checker import process_stock_update
from components.views import BoostPanelView

# นำเข้า View ปุ่มเติมเงินมาลงทะเบียนตั้งแต่เริ่มต้นw
from cogs.topup_and_admin import TopupPanelButtonView

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BANNER_IMAGE_URL = os.getenv("BANNER_IMAGE_URL")
CUSTOM_PRICE_1M = os.getenv("CUSTOM_PRICE_1M", "7.00")
CUSTOM_PRICE_3M = os.getenv("CUSTOM_PRICE_3M", "25.00")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
STOCK_WEBHOOK_URL = os.getenv("STOCK_WEBHOOK_URL")
STOCK_NOTIFY_ROLE_ID = os.getenv("STOCK_NOTIFY_ROLE_ID")
STATS_FILE = "stats.json"

EMOJI_PANEL_BOOST = os.getenv("EMOJI_PANEL_BOOST", "<a:245_boost:1175394139504910336>")
EMOJI_PANEL_REMAIN = os.getenv("EMOJI_PANEL_REMAIN", "<a:botsever60:1184927829893337158>")
EMOJI_PANEL_TOTAL = os.getenv("EMOJI_PANEL_TOTAL", "<a:botsever16:1184852397982502922>")

ALLOWED_ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ALLOWED_ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# --- JSON STATS ---
def load_data():
    if not os.path.exists(STATS_FILE):
        default_data = {"total_1m": 0, "total_3m": 0, "panel_channel_id": None, "panel_message_id": None}
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        return default_data
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_boost_stats(month: int, amount: int):
    data = load_data()
    if month == 1:
        data["total_1m"] = data.get("total_1m", 0) + amount
    elif month == 3:
        data["total_3m"] = data.get("total_3m", 0) + amount
    save_data(data)
import aiohttp

# ใช้ API บูสต์ของ PlanariaShop แทน Worrakit (ตั้งค่า PLANARIA_API_KEY ในไฟล์ .env)
PLANARIA_API_KEY = os.getenv("PLANARIA_API_KEY")
PLANARIA_API_URL = "https://www.planariashop.com/api/discordboost.php"

# สถานะจาก PlanariaShop ที่ต้องแปลงให้บอทเข้าใจ
# partial = บูสต์ไม่ครบ (PlanariaShop คืนส่วนที่ขาดให้ร้านแล้ว) บอทจึงคืนส่วนที่ขาดให้ลูกค้าเหมือนกรณีสำเร็จ
STATUS_MAP = {"partial": "completed", "partial_refunded": "completed", "refunded": "failed"}


class PlanariaBoostClient:
    """เรียก api/discordboost.php แล้วแปลงผลให้ตรงกับที่บอทใช้อยู่ (ชื่อเมธอดเหมือนเดิม)"""

    def __init__(self, api_key: str, url: str = PLANARIA_API_URL):
        self.api_key = api_key
        self.url = url

    async def _call(self, payload: dict) -> dict:
        body = {"keyapi": self.api_key, **payload}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json=body, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                try:
                    return await resp.json(content_type=None)
                except Exception:
                    return {"status": "error", "message": f"ระบบตอบกลับผิดรูปแบบ (HTTP {resp.status})"}

    async def get_stock(self):
        res = await self._call({"action": "stock"})
        return {"stock": res.get("stock") or {"boost_1m": 0, "boost_3m": 0}}

    async def buy_boost(self, invite_link: str, month: int, amount: int):
        res = await self._call({"action": "order", "invite": invite_link, "month": month, "amount": amount})
        if res.get("status") == "success":
            return {"oders_id": res.get("order_id"), "message": res.get("message", "")}
        return {"message": res.get("message", "สั่งซื้อไม่สำเร็จ")}

    async def get_order_history(self, order_id: str):
        res = await self._call({"action": "status", "order_id": order_id})
        if res.get("status") != "success":
            # ตอบผิดพลาดชั่วคราว ให้บอทรอรอบถัดไป (ห้ามคืนเงินเพราะเรื่องเครือข่าย)
            return {"status": "", "data": {}}
        d = res.get("data") or {}
        order_status = str(d.get("status", "")).lower()
        return {
            "status": STATUS_MAP.get(order_status, order_status),
            "data": {
                "orderId": d.get("order_id", order_id),
                "boostSuccess": d.get("boost_success") or 0,
                "boostAmount": d.get("amount") or 0,
                "guildInfo": {"guildName": d.get("guild_name") or "ไม่ทราบชื่อเซิร์ฟเวอร์"},
            },
        }


api_client = PlanariaBoostClient(api_key=PLANARIA_API_KEY)

async def build_boost_embed(current_stock=None):
    if current_stock is None:
        stock_res = await api_client.get_stock()
        current_stock = stock_res.get("stock", {})
        
    data = load_data()
    p_1m_val = int(float(CUSTOM_PRICE_1M))
    p_3m_val = int(float(CUSTOM_PRICE_3M))

    embed = discord.Embed(color=discord.Color.from_rgb(88, 101, 242))
    
    # 1 Month
    embed.add_field(name=f"{EMOJI_PANEL_BOOST} 1 Month", value=f"```fix\n{p_1m_val:<2} บาท\n```", inline=True)
    embed.add_field(name=f"{EMOJI_PANEL_REMAIN} เหลือจำนวน", value=f"```fix\n{current_stock.get('boost_1m', 0):<2} บูสต์\n```", inline=True)
    embed.add_field(name=f"{EMOJI_PANEL_TOTAL} บูสต์แล้วทั้งหมด", value=f"```fix\n{data.get('total_1m', 0):<2} บูสต์\n```", inline=True)

    # 3 Month
    embed.add_field(name=f"{EMOJI_PANEL_BOOST} 3 Month", value=f"```fix\n{p_3m_val:<2} บาท\n```", inline=True)
    embed.add_field(name=f"{EMOJI_PANEL_REMAIN} เหลือจำนวน", value=f"```fix\n{current_stock.get('boost_3m', 0):<2} บูสต์\n```", inline=True)
    embed.add_field(name=f"{EMOJI_PANEL_TOTAL} บูสต์แล้วทั้งหมด", value=f"```fix\n{data.get('total_3m', 0):<2} บูสต์\n```", inline=True)

    if BANNER_IMAGE_URL:
        embed.set_image(url=BANNER_IMAGE_URL)
    return embed

async def update_main_panel(bot_instance: commands.Bot, current_stock=None):
    data = load_data()
    channel_id = data.get("panel_channel_id")
    message_id = data.get("panel_message_id")
    
    new_embed = await build_boost_embed(current_stock=current_stock)
    
    if channel_id and message_id:
        try:
            channel = bot_instance.get_channel(channel_id) or await bot_instance.fetch_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=new_embed, view=BoostPanelView(bot_instance=bot_instance, api_client=api_client, helpers=helpers))
            return
        except discord.NotFound:
            print("[Panel Notice]: ไม่พบข้อความแผงควบคุมเดิม กำลังสร้างใหม่...")
        except Exception as e:
            print(f"[Panel Update Error]: {e}")
            return

    if channel_id:
        try:
            channel = bot_instance.get_channel(channel_id) or await bot_instance.fetch_channel(channel_id)
            new_msg = await channel.send(embed=new_embed, view=BoostPanelView(bot_instance=bot_instance, api_client=api_client, helpers=helpers))
            data["panel_message_id"] = new_msg.id
            save_data(data)
        except Exception as e:
            print(f"[Panel Recreate Error]: {e}")

helpers = {
    "custom_price_1m": CUSTOM_PRICE_1M,
    "custom_price_3m": CUSTOM_PRICE_3M,
    "log_channel_id": LOG_CHANNEL_ID,
    "add_boost_stats": add_boost_stats,
    "update_main_panel": update_main_panel
}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(seconds=600)
async def stock_monitor_task():
    try:
        stock_res = await api_client.get_stock()
        current_stock = stock_res.get("stock", {})
        
        await process_stock_update(
            current_stock=current_stock,
            webhook_url=STOCK_WEBHOOK_URL,
            notify_role_id=STOCK_NOTIFY_ROLE_ID
        )
        
        await update_main_panel(bot, current_stock=current_stock)
    except Exception as e:
        print(f"[Stock Monitor Loop Error]: {e}")

@stock_monitor_task.before_loop
async def before_monitor():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    # ลงทะเบียน View ทั้งสองแบบให้ทำงานตลอดเวลา (Persistent) แม้บอทจะรีสตาร์ต
    bot.add_view(BoostPanelView(bot_instance=bot, api_client=api_client, helpers=helpers))
    bot.add_view(TopupPanelButtonView())
    
    # ป้องกันการโหลดซ้ำกรณี Reconnect
    if "cogs.topup_and_admin" not in bot.extensions:
        try:
            await bot.load_extension("cogs.topup_and_admin")
            print("✅ โหลดระบบเติมเงินและจัดการพ้อยท์เรียบร้อย")
        except Exception as e:
            print(f"❌ โหลดโมดูลไม่สำเร็จ: {e}")

    await bot.tree.sync()
    if not stock_monitor_task.is_running():
        stock_monitor_task.start()
    print(f"✅ บอทพร้อมทำงาน: {bot.user}")

@bot.tree.command(name="setup_boost", description="ติดตั้งแผงสั่งซื้อบูสต์เซิร์ฟเวอร์ (Admin)")
async def setup_boost(interaction: discord.Interaction):
    if interaction.user.id not in ALLOWED_ADMIN_IDS:
        return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    embed = await build_boost_embed()
    view = BoostPanelView(bot_instance=bot, api_client=api_client, helpers=helpers)
    panel_msg = await interaction.channel.send(embed=embed, view=view)

    data = load_data()
    data["panel_channel_id"] = interaction.channel.id
    data["panel_message_id"] = panel_msg.id
    save_data(data)

    await interaction.followup.send("✅ ติดตั้งแผงสั่งซื้อบูสต์เรียบร้อยแล้ว!", ephemeral=True)

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)