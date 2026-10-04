import discord
from discord.ext import commands
from discord import ui
import sqlite3
import random
import asyncio
import os
from datetime import datetime, timedelta


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
DB_FILE = "stock_bot.db"

USD_VND = 26_000
BTC_VND = 2_800_000_000


# =========================================================
# BOT
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    vnd INTEGER DEFAULT 0,
    usd REAL DEFAULT 0,
    btc REAL DEFAULT 0,
    bank_vnd INTEGER DEFAULT 0,
    bank_usd REAL DEFAULT 0,
    last_daily TEXT
)
""")

# Migrate old database
for column, definition in [
    ("bank_vnd", "INTEGER DEFAULT 0"),
    ("bank_usd", "REAL DEFAULT 0")
]:
    try:
        cursor.execute(
            f"ALTER TABLE users ADD COLUMN {column} {definition}"
        )
    except sqlite3.OperationalError:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS exchange_cash (
    user_id INTEGER,
    exchange TEXT,
    vnd INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, exchange)
)
""")

db.commit()


# =========================================================
# STOCKS
# =========================================================

STOCKS = {
    "NASDAQ": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("NVDA", "NVIDIA"),
        ("TSLA", "Tesla"),
        ("AMZN", "Amazon"),
        ("META", "Meta")
    ],
    "NYSE": [
        ("JPM", "JPMorgan Chase"),
        ("KO", "Coca-Cola"),
        ("DIS", "Disney"),
        ("WMT", "Walmart"),
        ("V", "Visa")
    ],
    "HOSE": [
        ("VIC", "Vingroup"),
        ("VHM", "Vinhomes"),
        ("FPT", "FPT"),
        ("HPG", "Hoa Phat"),
        ("VCB", "Vietcombank")
    ],
    "TSE": [
        ("7203", "Toyota"),
        ("9984", "SoftBank"),
        ("6758", "Sony")
    ],
    "HKEX": [
        ("0700", "Tencent"),
        ("9988", "Alibaba"),
        ("3690", "Meituan")
    ],
    "HNX": [
        ("PVS", "PTSC"),
        ("SHS", "SHS"),
        ("CEO", "CEO Group")
    ],
    "LSE": [
        ("SHEL", "Shell"),
        ("AZN", "AstraZeneca"),
        ("HSBA", "HSBC")
    ],
    "SSE": [
        ("600519", "Kweichow Moutai"),
        ("601318", "Ping An")
    ],
    "KRX": [
        ("005930", "Samsung Electronics"),
        ("000660", "SK Hynix"),
        ("035420", "NAVER")
    ],
    "SGX": [
        ("D05", "DBS"),
        ("O39", "OCBC"),
        ("U11", "UOB")
    ],
    "UPCoM": [
        ("ACV", "Airports Corporation"),
        ("VEA", "Vietnam Engine")
    ]
}

EXCHANGES = list(STOCKS.keys())


# =========================================================
# MONEY
# =========================================================

def money(amount):
    return f"{int(amount):,}".replace(",", ".")


def usd(amount):
    return f"{float(amount):,.2f}"


def btc(amount):
    return f"{float(amount):.8f}"


def parse_money(value):
    value = str(value).strip().lower()

    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "t": 1_000_000_000_000
    }

    try:
        if not value:
            return None

        if value[-1] in multipliers:
            number = float(value[:-1])
            amount = int(number * multipliers[value[-1]])
        else:
            value = value.replace(".", "")
            value = value.replace(",", "")
            amount = int(value)

        if amount < 0:
            return None

        return amount

    except (ValueError, IndexError):
        return None


def parse_usd(value):
    value = str(value).strip().lower()

    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000
    }

    try:
        if not value:
            return None

        if value[-1] in multipliers:
            number = float(value[:-1])
            amount = number * multipliers[value[-1]]
        else:
            amount = float(value.replace(",", ""))

        if amount < 0:
            return None

        return amount

    except (ValueError, IndexError):
        return None


# =========================================================
# USER DATABASE
# =========================================================

def ensure_user(user_id):
    cursor.execute(
        """
        INSERT OR IGNORE INTO users
        (user_id, vnd, usd, btc, bank_vnd, bank_usd, last_daily)
        VALUES (?, 0, 0, 0, 0, 0, NULL)
        """,
        (user_id,)
    )
    db.commit()


def get_wallet(user_id):
    ensure_user(user_id)

    cursor.execute(
        """
        SELECT vnd, usd, btc, bank_vnd, bank_usd
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    if not row:
        return 0, 0.0, 0.0, 0, 0.0

    return (
        int(row[0] or 0),
        float(row[1] or 0),
        float(row[2] or 0),
        int(row[3] or 0),
        float(row[4] or 0)
    )


def get_vnd(user_id):
    return get_wallet(user_id)[0]


def get_usd(user_id):
    return get_wallet(user_id)[1]


def get_btc(user_id):
    return get_wallet(user_id)[2]


def get_bank_vnd(user_id):
    return get_wallet(user_id)[3]


def get_bank_usd(user_id):
    return get_wallet(user_id)[4]


def add_vnd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET vnd = vnd + ?
        WHERE user_id = ?
        """,
        (int(amount), user_id)
    )
    db.commit()


def add_usd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET usd = usd + ?
        WHERE user_id = ?
        """,
        (float(amount), user_id)
    )
    db.commit()


def set_vnd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET vnd = ?
        WHERE user_id = ?
        """,
        (int(amount), user_id)
    )
    db.commit()


def set_usd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET usd = ?
        WHERE user_id = ?
        """,
        (float(amount), user_id)
    )
    db.commit()


def add_bank_vnd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET bank_vnd = bank_vnd + ?
        WHERE user_id = ?
        """,
        (int(amount), user_id)
    )
    db.commit()


def add_bank_usd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET bank_usd = bank_usd + ?
        WHERE user_id = ?
        """,
        (float(amount), user_id)
    )
    db.commit()


def set_bank_vnd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET bank_vnd = ?
        WHERE user_id = ?
        """,
        (int(amount), user_id)
    )
    db.commit()


def set_bank_usd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET bank_usd = ?
        WHERE user_id = ?
        """,
        (float(amount), user_id)
    )
    db.commit()


# =========================================================
# EXCHANGE CASH
# =========================================================

def get_exchange_cash(user_id, exchange):
    cursor.execute(
        """
        SELECT vnd
        FROM exchange_cash
        WHERE user_id = ?
        AND exchange = ?
        """,
        (user_id, exchange)
    )

    row = cursor.fetchone()

    if row:
        return int(row[0] or 0)

    return 0


def set_exchange_cash(user_id, exchange, amount):
    cursor.execute(
        """
        INSERT INTO exchange_cash
        (user_id, exchange, vnd)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, exchange)
        DO UPDATE SET vnd = excluded.vnd
        """,
        (user_id, exchange, int(amount))
    )
    db.commit()


# =========================================================
# MARKET MOVEMENT
# =========================================================

def generate_movement(capital):
    if capital <= 0:
        return 0

    if random.random() < 0.70:
        percent = random.uniform(0.005, 0.05)
    else:
        percent = random.uniform(-0.02, -0.005)

    delta = int(capital * percent)

    if delta == 0:
        delta = 1000 if percent > 0 else -1000

    return delta


# =========================================================
# SESSIONS
# =========================================================

sessions = {}


# =========================================================
# MARKET EMBED
# =========================================================

def make_market_embed(session):
    capital = get_exchange_cash(
        session["user_id"],
        session["exchange"]
    )

    delta = session.get("delta", 0)

    if delta > 0:
        change_text = f"🟢 +{money(delta)} VND"
    elif delta < 0:
        change_text = f"🔴 -{money(abs(delta))} VND"
    else:
        change_text = "⚪ 0 VND"

    embed = discord.Embed(
        color=(
            discord.Color.green()
            if delta >= 0
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="🏦 Sàn",
        value=session["exchange"],
        inline=True
    )

    embed.add_field(
        name="📈 Cổ phiếu",
        value=session["symbol"],
        inline=True
    )

    embed.add_field(
        name="🏢 Công ty",
        value=session["company"],
        inline=True
    )

    embed.add_field(
        name="💰 Vốn hiện tại",
        value=f"**{money(capital)} VND**",
        inline=False
    )

    embed.add_field(
        name="📊 Thay đổi",
        value=change_text,
        inline=False
    )

    return embed


# =========================================================
# MARKET VIEW
# =========================================================

class MarketView(ui.View):

    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    async def interaction_check(self, interaction):
        if interaction.user.id != self.session["user_id"]:
            await interaction.response.send_message(
                "❌ Đây không phải bảng giao dịch của bạn.",
                ephemeral=True
            )
            return False

        return True

    @ui.button(
        label="Take",
        emoji="💸",
        style=discord.ButtonStyle.green
    )
    async def take(self, interaction, button):

        message_id = interaction.message.id

        session = sessions.get(message_id)

        if session is None:
            await interaction.response.send_message(
                "❌ Phiên giao dịch không còn tồn tại.",
                ephemeral=True
            )
            return

        if session["ended"]:
            await interaction.response.send_message(
                "❌ Phiên giao dịch đã kết thúc.",
                ephemeral=True
            )
            return

        if session["crashed"]:
            await interaction.response.send_message(
                "💥 Sàn đã sập.",
                ephemeral=True
            )
            return

        user_id = session["user_id"]
        exchange = session["exchange"]

        original_capital = session["original_capital"]

        amount = get_exchange_cash(
            user_id,
            exchange
        )

        if amount <= 0:
            await interaction.response.send_message(
                "❌ Không còn tiền trên sàn.",
                ephemeral=True
            )
            return

        difference = amount - original_capital

        if difference > 0:
            profit_text = f"+{money(difference)} VND"
            loss_text = "N/A"
        elif difference < 0:
            profit_text = "N/A"
            loss_text = f"-{money(abs(difference))} VND"
        else:
            profit_text = "N/A"
            loss_text = "N/A"

        session["ended"] = True

        market_task = session.get("market_task")
        if market_task and not market_task.done():
            market_task.cancel()

        crash_task = session.get("crash_task")
        if crash_task and not crash_task.done():
            crash_task.cancel()

        set_exchange_cash(
            user_id,
            exchange,
            0
        )

        add_vnd(
            user_id,
            amount
        )

        sessions.pop(
            message_id,
            None
        )

        embed = discord.Embed(
            color=(
                discord.Color.green()
                if difference >= 0
                else discord.Color.red()
            )
        )

        embed.add_field(
            name="🏦 Sàn",
            value=exchange,
            inline=True
        )

        embed.add_field(
            name="📈 Cổ phiếu",
            value=session["symbol"],
            inline=True
        )

        embed.add_field(
            name="🏢 Công ty",
            value=session["company"],
            inline=True
        )

        embed.add_field(
            name="💰 Tiền nhận về",
            value=f"**{money(amount)} VND**",
            inline=False
        )

        embed.add_field(
            name="🟢 Tiền lãi",
            value=f"**{profit_text}**",
            inline=True
        )

        embed.add_field(
            name="🔴 Tiền lỗ",
            value=f"**{loss_text}**",
            inline=True
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None
        )


# =========================================================
# MARKET LOOP
# =========================================================

async def market_loop(session):
    try:
        while not session["ended"] and not session["crashed"]:

            await asyncio.sleep(1)

            if session["ended"] or session["crashed"]:
                break

            user_id = session["user_id"]
            exchange = session["exchange"]

            current_money = get_exchange_cash(
                user_id,
                exchange
            )

            if current_money <= 0:
                break

            delta = generate_movement(current_money)

            new_money = max(
                0,
                current_money + delta
            )

            set_exchange_cash(
                user_id,
                exchange,
                new_money
            )

            session["capital"] = new_money
            session["delta"] = delta

            message = session.get("message")

            if message is None:
                continue

            try:
                await message.edit(
                    content=None,
                    embed=make_market_embed(session),
                    view=session["view"]
                )

            except discord.NotFound:
                session["ended"] = True
                sessions.pop(message.id, None)
                break

            except discord.HTTPException as e:
                print(f"⚠️ Market edit error: {e}")

    except asyncio.CancelledError:
        return

    except Exception as e:
        print(
            f"❌ MARKET LOOP ERROR: "
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# CRASH TIMER
# =========================================================

async def crash_timer(session):
    try:
        wait_time = random.randint(30, 60)

        print(
            f"💥 Crash timer: "
            f"{session['exchange']} "
            f"{session['symbol']} "
            f"-> {wait_time}s"
        )

        await asyncio.sleep(wait_time)

        if session["ended"] or session["crashed"]:
            return

        user_id = session["user_id"]
        exchange = session["exchange"]

        current_money = get_exchange_cash(
            user_id,
            exchange
        )

        if current_money <= 0:
            return

        loss_percent = random.uniform(0.40, 1.00)

        crash_loss = int(
            current_money * loss_percent
        )

        remaining = max(
            0,
            current_money - crash_loss
        )

        set_exchange_cash(
            user_id,
            exchange,
            remaining
        )

        session["capital"] = remaining
        session["crash_loss"] = crash_loss
        session["crashed"] = True
        session["ended"] = True

        market_task = session.get("market_task")

        if market_task and not market_task.done():
            market_task.cancel()

        message = session.get("message")

        if message:
            embed = discord.Embed(
                color=discord.Color.red()
            )

            embed.add_field(
                name="💥 Sập sàn",
                value=exchange,
                inline=False
            )

            embed.add_field(
                name="📈 Cổ phiếu",
                value=session["symbol"],
                inline=True
            )

            embed.add_field(
                name="🏢 Công ty",
                value=session["company"],
                inline=True
            )

            embed.add_field(
                name="💸 Tiền mất",
                value=f"**-{money(crash_loss)} VND**",
                inline=False
            )

            embed.add_field(
                name="💰 Còn lại",
                value=f"**{money(remaining)} VND**",
                inline=False
            )

            await message.edit(
                content=None,
                embed=embed,
                view=None
            )

            sessions.pop(
                message.id,
                None
            )

    except asyncio.CancelledError:
        return

    except Exception as e:
        print(
            f"❌ CRASH ERROR: "
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# CAPITAL MODAL
# =========================================================

class CapitalModal(ui.Modal):

    def __init__(
        self,
        user_id,
        exchange,
        symbol,
        company
    ):
        super().__init__(
            title="Nhập số tiền đầu tư"
        )

        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.company = company

        self.amount = ui.TextInput(
            label="Số tiền",
            placeholder="VD: 100k / 10m / 1b / 1t",
            required=True
        )

        self.add_item(self.amount)

    async def on_submit(self, interaction):

        capital = parse_money(self.amount.value)

        if capital is None or capital <= 0:
            await interaction.response.send_message(
                "❌ Số tiền không hợp lệ.",
                ephemeral=True
            )
            return

        wallet = get_vnd(self.user_id)

        if capital > wallet:
            await interaction.response.send_message(
                f"❌ Bạn chỉ có **{money(wallet)} VND**.",
                ephemeral=True
            )
            return

        # Không cho mở 2 phiên cùng một sàn
        if get_exchange_cash(
            self.user_id,
            self.exchange
        ) > 0:
            await interaction.response.send_message(
                "❌ Bạn đang có tiền trên sàn này rồi.",
                ephemeral=True
            )
            return

        set_vnd(
            self.user_id,
            wallet - capital
        )

        set_exchange_cash(
            self.user_id,
            self.exchange,
            capital
        )

        session = {
            "user_id": self.user_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "company": self.company,
            "original_capital": capital,
            "capital": capital,
            "delta": 0,
            "crashed": False,
            "ended": False,
            "crash_loss": 0,
            "message": None,
            "view": None,
            "market_task": None,
            "crash_task": None
        }

        market_view = MarketView(session)
        session["view"] = market_view

        await interaction.response.edit_message(
            content=None,
            embed=make_market_embed(session),
            view=market_view
        )

        try:
            message = await interaction.original_response()
        except Exception:
            message = interaction.message

        session["message"] = message

        sessions[message.id] = session

        session["market_task"] = asyncio.create_task(
            market_loop(session)
        )

        session["crash_task"] = asyncio.create_task(
            crash_timer(session)
        )


# =========================================================
# STOCK SELECT
# =========================================================

class StockSelect(ui.Select):

    def __init__(self, exchange):
        self.exchange = exchange

        options = []

        for symbol, company in STOCKS[exchange]:
            options.append(
                discord.SelectOption(
                    label=symbol,
                    description=company
                )
            )

        super().__init__(
            placeholder="Chọn cổ phiếu",
            options=options
        )

    async def callback(self, interaction):

        symbol = self.values[0]
        company = None

        for s, c in STOCKS[self.exchange]:
            if s == symbol:
                company = c
                break

        modal = CapitalModal(
            interaction.user.id,
            self.exchange,
            symbol,
            company
        )

        await interaction.response.send_modal(modal)


class StockSelectView(ui.View):

    def __init__(self, exchange):
        super().__init__(timeout=120)
        self.add_item(StockSelect(exchange))


# =========================================================
# EXCHANGE SELECT
# =========================================================

class ExchangeSelect(ui.Select):

    def __init__(self):
        options = []

        for exchange in EXCHANGES:
            options.append(
                discord.SelectOption(
                    label=exchange,
                    value=exchange
                )
            )

        super().__init__(
            placeholder="Chọn sàn",
            options=options
        )

    async def callback(self, interaction):

        exchange = self.values[0]

        embed = discord.Embed(
            title=f"🏦 {exchange}",
            description="Chọn cổ phiếu muốn giao dịch."
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=StockSelectView(exchange)
        )


class ExchangeView(ui.View):

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ExchangeSelect())


# =========================================================
# !STOCK
# =========================================================

@bot.command()
async def stock(ctx):

    ensure_user(ctx.author.id)

    embed = discord.Embed(
        title="📈 STOCK MARKET",
        description="Chọn sàn giao dịch bên dưới.",
        color=discord.Color.blurple()
    )

    await ctx.send(
        embed=embed,
        view=ExchangeView()
    )


# =========================================================
# !BALANCE
# =========================================================

@bot.command()
async def balance(ctx):

    user_id = ctx.author.id

    vnd, usd_amount, btc_amount, bank_vnd, bank_usd = get_wallet(
        user_id
    )

    total_vnd = (
        vnd
        + bank_vnd
        + (usd_amount + bank_usd) * USD_VND
        + btc_amount * BTC_VND
    )

    embed = discord.Embed(
        color=discord.Color.green()
    )

    embed.add_field(
        name="💵 Ví VND",
        value=f"**{money(vnd)} VND**",
        inline=False
    )

    embed.add_field(
        name="💲 Ví USD",
        value=f"**${usd(usd_amount)}**",
        inline=False
    )

    embed.add_field(
        name="₿ Bitcoin",
        value=f"**{btc(btc_amount)} BTC**",
        inline=False
    )

    embed.add_field(
        name="🏦 Ngân hàng VND",
        value=f"**{money(bank_vnd)} VND**",
        inline=False
    )

    embed.add_field(
        name="🏦 Ngân hàng USD",
        value=f"**${usd(bank_usd)}**",
        inline=False
    )

    embed.add_field(
        name="📊 Tổng tài sản",
        value=f"**{money(total_vnd)} VND**",
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# !PAY
# =========================================================

@bot.command()
async def pay(ctx, member: discord.Member, amount: str):

    amount = parse_money(amount)

    if amount is None or amount <= 0:
        await ctx.send("❌ Số tiền không hợp lệ.")
        return

    if member.id == ctx.author.id:
        await ctx.send(
            "❌ Không thể chuyển tiền cho chính mình."
        )
        return

    sender_money = get_vnd(ctx.author.id)

    if amount > sender_money:
        await ctx.send(
            f"❌ Bạn chỉ có **{money(sender_money)} VND**."
        )
        return

    add_vnd(ctx.author.id, -amount)
    add_vnd(member.id, amount)

    await ctx.send(
        f"💸 **{ctx.author.display_name}** đã chuyển "
        f"**{money(amount)} VND** cho "
        f"**{member.display_name}**."
    )


# =========================================================
# !DAILY
# =========================================================

@bot.command()
async def daily(ctx):

    user_id = ctx.author.id
    ensure_user(user_id)

    cursor.execute(
        """
        SELECT last_daily
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    now = datetime.now()

    if row and row[0]:

        try:
            last_daily = datetime.fromisoformat(row[0])
            cooldown = timedelta(hours=24)

            if now - last_daily < cooldown:

                remaining = cooldown - (now - last_daily)

                hours = int(
                    remaining.total_seconds() // 3600
                )

                minutes = int(
                    (remaining.total_seconds() % 3600) // 60
                )

                await ctx.send(
                    f"⏳ Bạn đã nhận Daily rồi. "
                    f"Còn **{hours}h {minutes}m**."
                )
                return

        except ValueError:
            pass

    reward = random.randint(50_000, 500_000)

    add_vnd(user_id, reward)

    cursor.execute(
        """
        UPDATE users
        SET last_daily = ?
        WHERE user_id = ?
        """,
        (now.isoformat(), user_id)
    )

    db.commit()

    await ctx.send(
        f"🎁 Bạn nhận được "
        f"**{money(reward)} VND** từ Daily!"
    )


# =========================================================
# !DEPOSIT
# !deposit vnd 100k
# !deposit usd 100
# =========================================================

@bot.command()
async def deposit(ctx, currency: str, amount: str):

    currency = currency.lower()

    if currency == "vnd":

        value = parse_money(amount)

        if value is None or value <= 0:
            await ctx.send("❌ Số tiền VND không hợp lệ.")
            return

        wallet = get_vnd(ctx.author.id)

        if value > wallet:
            await ctx.send(
                f"❌ Ví VND chỉ có **{money(wallet)} VND**."
            )
            return

        add_vnd(ctx.author.id, -value)
        add_bank_vnd(ctx.author.id, value)

        await ctx.send(
            f"🏦 Đã gửi **{money(value)} VND** "
            f"từ ví vào ngân hàng VND."
        )
        return

    if currency == "usd":

        value = parse_usd(amount)

        if value is None or value <= 0:
            await ctx.send("❌ Số tiền USD không hợp lệ.")
            return

        wallet = get_usd(ctx.author.id)

        if value > wallet:
            await ctx.send(
                f"❌ Ví USD chỉ có **${usd(wallet)}**."
            )
            return

        add_usd(ctx.author.id, -value)
        add_bank_usd(ctx.author.id, value)

        await ctx.send(
            f"🏦 Đã gửi **${usd(value)}** "
            f"từ ví vào ngân hàng USD."
        )
        return

    await ctx.send(
        "❌ Loại tiền không hợp lệ. Dùng `vnd` hoặc `usd`."
    )


# =========================================================
# !WITHDRAW
# !withdraw vnd 100k
# !withdraw usd 100
# =========================================================

@bot.command()
async def withdraw(ctx, currency: str, amount: str):

    currency = currency.lower()

    if currency == "vnd":

        value = parse_money(amount)

        if value is None or value <= 0:
            await ctx.send("❌ Số tiền VND không hợp lệ.")
            return

        bank = get_bank_vnd(ctx.author.id)

        if value > bank:
            await ctx.send(
                f"❌ Ngân hàng VND chỉ có **{money(bank)} VND**."
            )
            return

        add_bank_vnd(ctx.author.id, -value)
        add_vnd(ctx.author.id, value)

        await ctx.send(
            f"💵 Đã rút **{money(value)} VND** "
            f"từ ngân hàng về ví VND."
        )
        return

    if currency == "usd":

        value = parse_usd(amount)

        if value is None or value <= 0:
            await ctx.send("❌ Số tiền USD không hợp lệ.")
            return

        bank = get_bank_usd(ctx.author.id)

        if value > bank:
            await ctx.send(
                f"❌ Ngân hàng USD chỉ có **${usd(bank)}**."
            )
            return

        add_bank_usd(ctx.author.id, -value)
        add_usd(ctx.author.id, value)

        await ctx.send(
            f"💵 Đã rút **${usd(value)}** "
            f"từ ngân hàng về ví USD."
        )
        return

    await ctx.send(
        "❌ Loại tiền không hợp lệ. Dùng `vnd` hoặc `usd`."
    )


# =========================================================
# !EXCHANGE
# !exchange vnd usd 260k
# !exchange usd vnd 10
# =========================================================

@bot.command()
async def exchange(ctx, from_currency: str, to_currency: str, amount: str):

    from_currency = from_currency.lower()
    to_currency = to_currency.lower()

    if from_currency == to_currency:
        await ctx.send(
            "❌ Không thể đổi cùng một loại tiền."
        )
        return

    if {
        from_currency,
        to_currency
    } != {"vnd", "usd"}:

        await ctx.send(
            "❌ Chỉ hỗ trợ `vnd` ↔ `usd`."
        )
        return

    user_id = ctx.author.id

    # VND -> USD
    if from_currency == "vnd":

        value = parse_money(amount)

        if value is None or value <= 0:
            await ctx.send("❌ Số tiền VND không hợp lệ.")
            return

        wallet_vnd = get_vnd(user_id)

        if value > wallet_vnd:
            await ctx.send(
                f"❌ Ví VND chỉ có **{money(wallet_vnd)} VND**."
            )
            return

        usd_received = value / USD_VND

        add_vnd(user_id, -value)
        add_usd(user_id, usd_received)

        await ctx.send(
            f"💱 Đã đổi **{money(value)} VND** → "
            f"**${usd(usd_received)} USD**.\n"
            f"📌 Tỷ giá: **1 USD = {money(USD_VND)} VND**"
        )
        return

    # USD -> VND
    value = parse_usd(amount)

    if value is None or value <= 0:
        await ctx.send("❌ Số tiền USD không hợp lệ.")
        return

    wallet_usd = get_usd(user_id)

    if value > wallet_usd:
        await ctx.send(
            f"❌ Ví USD chỉ có **${usd(wallet_usd)}**."
        )
        return

    vnd_received = int(value * USD_VND)

    add_usd(user_id, -value)
    add_vnd(user_id, vnd_received)

    await ctx.send(
        f"💱 Đã đổi **${usd(value)} USD** → "
        f"**{money(vnd_received)} VND**.\n"
        f"📌 Tỷ giá: **1 USD = {money(USD_VND)} VND**"
    )


# =========================================================
# !HELP
# =========================================================

@bot.command(name="help")
async def help_command(ctx):

    embed = discord.Embed(
        title="📖 Danh sách lệnh",
        color=discord.Color.blurple()
    )

    embed.description = (
        "`!help` — Xem danh sách lệnh\n"
        "`!stock` — Mở sàn giao dịch\n"
        "`!balance` — Xem toàn bộ tài sản\n"
        "`!pay @user <số tiền>` — Chuyển VND cho người khác\n"
        "`!daily` — Nhận Daily 24 giờ/lần\n\n"

        "🏦 **NGÂN HÀNG**\n"
        "`!deposit vnd <số tiền>` — Ví VND → Ngân hàng VND\n"
        "`!withdraw vnd <số tiền>` — Ngân hàng VND → Ví VND\n"
        "`!deposit usd <số tiền>` — Ví USD → Ngân hàng USD\n"
        "`!withdraw usd <số tiền>` — Ngân hàng USD → Ví USD\n\n"

        "💱 **ĐỔI TIỀN**\n"
        "`!exchange vnd usd <số tiền>` — VND → USD\n"
        "`!exchange usd vnd <số tiền>` — USD → VND\n"
        f"Tỷ giá: `1 USD = {money(USD_VND)} VND`\n\n"

        "💡 **Nhập tiền VND:**\n"
        "`100k` `10m` `1b` `1t`\n\n"

        "💡 **Nhập USD:**\n"
        "`100` `100.50` `1k` `10m`"
    )

    await ctx.send(embed=embed)


# =========================================================
# COMMAND ERROR
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"❌ Thiếu tham số.\n"
            f"Dùng `!help` để xem cách dùng lệnh."
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ Tham số không hợp lệ. Dùng `!help` để xem cách dùng."
        )
        return

    print(
        f"❌ COMMAND ERROR: "
        f"{type(error).__name__}: {error}"
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Đăng nhập: {bot.user}"
    )

    print(
        f"🆔 Bot ID: {bot.user.id}"
    )


# =========================================================
# MESSAGE
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    await bot.process_commands(message)


# =========================================================
# RUN
# =========================================================

if not TOKEN:

    print(
        "❌ Chưa có DISCORD_TOKEN hoặc TOKEN."
    )

else:

    bot.run(TOKEN)
