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

db = sqlite3.connect(DB_FILE)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    vnd INTEGER DEFAULT 0,
    usd REAL DEFAULT 0,
    btc REAL DEFAULT 0,
    last_daily TEXT
)
""")

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


def parse_money(value):
    value = str(value).strip().lower()

    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "t": 1_000_000_000_000
    }

    try:
        if value[-1] in multipliers:
            number = float(value[:-1])
            amount = int(
                number * multipliers[value[-1]]
            )
        else:
            value = value.replace(".", "")
            value = value.replace(",", "")
            amount = int(value)

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
        (user_id, vnd, usd, btc, last_daily)
        VALUES (?, 0, 0, 0, NULL)
        """,
        (user_id,)
    )

    db.commit()


def get_vnd(user_id):

    ensure_user(user_id)

    cursor.execute(
        """
        SELECT vnd
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    if row:
        return row[0]

    return 0


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
        return row[0]

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
        (
            user_id,
            exchange,
            int(amount)
        )
    )

    db.commit()


# =========================================================
# MARKET MOVEMENT
# =========================================================

def generate_movement(capital):

    if capital <= 0:
        return 0

    # 70% tăng
    if random.random() < 0.70:

        percent = random.uniform(
            0.005,
            0.05
        )

    # 30% giảm
    else:

        percent = random.uniform(
            -0.02,
            -0.005
        )

    delta = int(
        capital * percent
    )

    if delta == 0:

        if percent > 0:
            delta = 1000
        else:
            delta = -1000

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

    delta = session.get(
        "delta",
        0
    )

    if delta > 0:

        change_text = (
            f"🟢 +{money(delta)} VND"
        )

    elif delta < 0:

        change_text = (
            f"🔴 -{money(abs(delta))} VND"
        )

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

        super().__init__(
            timeout=None
        )

        self.session = session

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ):

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
    async def take(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        message_id = interaction.message.id

        session = sessions.get(
            message_id
        )

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

        # =============================================
        # VỐN BAN ĐẦU
        # =============================================

        original_capital = session[
            "original_capital"
        ]

        # =============================================
        # TIỀN HIỆN TẠI
        # =============================================

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

        # =============================================
        # TÍNH LỜI / LỖ
        # =============================================

        difference = (
            amount - original_capital
        )

        if difference > 0:

            profit_text = (
                f"+{money(difference)} VND"
            )

            loss_text = "N/A"

        elif difference < 0:

            profit_text = "N/A"

            loss_text = (
                f"-{money(abs(difference))} VND"
            )

        else:

            profit_text = "N/A"
            loss_text = "N/A"

        # =============================================
        # KẾT THÚC PHIÊN
        # =============================================

        session["ended"] = True

        # Dừng market
        market_task = session.get(
            "market_task"
        )

        if (
            market_task
            and not market_task.done()
        ):

            market_task.cancel()

        # Dừng crash timer
        crash_task = session.get(
            "crash_task"
        )

        if (
            crash_task
            and not crash_task.done()
        ):

            crash_task.cancel()

        # =============================================
        # XÓA TIỀN KHỎI SÀN
        # =============================================

        set_exchange_cash(
            user_id,
            exchange,
            0
        )

        # =============================================
        # TRẢ TIỀN VỀ VÍ
        # =============================================

        add_vnd(
            user_id,
            amount
        )

        # =============================================
        # XÓA SESSION
        # =============================================

        sessions.pop(
            message_id,
            None
        )

        # =============================================
        # BẢNG MỚI
        # =============================================

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

        # XÓA BẢNG CŨ
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

        while (
            not session["ended"]
            and not session["crashed"]
        ):

            await asyncio.sleep(1)

            if (
                session["ended"]
                or session["crashed"]
            ):
                break

            user_id = session["user_id"]
            exchange = session["exchange"]

            current_money = get_exchange_cash(
                user_id,
                exchange
            )

            if current_money <= 0:
                break

            delta = generate_movement(
                current_money
            )

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

            message = session.get(
                "message"
            )

            if message is None:
                continue

            try:

                await message.edit(
                    content=None,
                    embed=make_market_embed(
                        session
                    ),
                    view=session["view"]
                )

            except discord.NotFound:

                session["ended"] = True

                sessions.pop(
                    message.id,
                    None
                )

                break

            except discord.HTTPException as e:

                print(
                    f"⚠️ Market edit error: {e}"
                )

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

        # Sập random sau 30 - 60 giây
        wait_time = random.randint(
            30,
            60
        )

        print(
            f"💥 Crash timer: "
            f"{session['exchange']} "
            f"{session['symbol']} "
            f"-> {wait_time}s"
        )

        await asyncio.sleep(
            wait_time
        )

        if session["ended"]:
            return

        if session["crashed"]:
            return

        user_id = session["user_id"]
        exchange = session["exchange"]

        current_money = get_exchange_cash(
            user_id,
            exchange
        )

        if current_money <= 0:
            return

        # =============================================
        # MẤT 40% - 100%
        # =============================================

        loss_percent = random.uniform(
            0.40,
            1.00
        )

        crash_loss = int(
            current_money * loss_percent
        )

        remaining = max(
            0,
            current_money - crash_loss
        )

        # =============================================
        # LƯU TIỀN SAU SẬP
        # =============================================

        set_exchange_cash(
            user_id,
            exchange,
            remaining
        )

        session["capital"] = remaining
        session["crash_loss"] = crash_loss
        session["crashed"] = True
        session["ended"] = True

        # =============================================
        # DỪNG MARKET
        # =============================================

        market_task = session.get(
            "market_task"
        )

        if (
            market_task
            and not market_task.done()
        ):

            market_task.cancel()

        # =============================================
        # HIỂN THỊ SẬP SÀN
        # =============================================

        message = session.get(
            "message"
        )

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

        self.add_item(
            self.amount
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        capital = parse_money(
            self.amount.value
        )

        if (
            capital is None
            or capital <= 0
        ):

            await interaction.response.send_message(
                "❌ Số tiền không hợp lệ.",
                ephemeral=True
            )

            return

        wallet = get_vnd(
            self.user_id
        )

        if capital > wallet:

            await interaction.response.send_message(
                f"❌ Bạn chỉ có **{money(wallet)} VND**.",
                ephemeral=True
            )

            return

        # =============================================
        # TRỪ TIỀN VÍ
        # =============================================

        set_vnd(
            self.user_id,
            wallet - capital
        )

        # =============================================
        # ĐƯA TIỀN VÀO SÀN
        # =============================================

        set_exchange_cash(
            self.user_id,
            self.exchange,
            capital
        )

        # =============================================
        # SESSION
        # =============================================

        session = {
            "user_id": self.user_id,

            "exchange": self.exchange,
            "symbol": self.symbol,
            "company": self.company,

            # Vốn ban đầu
            "original_capital": capital,

            # Vốn hiện tại
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

        # =============================================
        # VIEW
        # =============================================

        market_view = MarketView(
            session
        )

        session["view"] = market_view

        # =============================================
        # BẢNG THỊ TRƯỜNG
        # =============================================

        await interaction.response.edit_message(
            content=None,
            embed=make_market_embed(
                session
            ),
            view=market_view
        )

        # =============================================
        # LẤY MESSAGE
        # =============================================

        try:

            message = await interaction.original_response()

        except Exception:

            message = interaction.message

        session["message"] = message

        # =============================================
        # LƯU SESSION
        # =============================================

        sessions[
            message.id
        ] = session

        # =============================================
        # MARKET TASK
        # =============================================

        session["market_task"] = asyncio.create_task(
            market_loop(
                session
            )
        )

        # =============================================
        # CRASH TASK
        # =============================================

        session["crash_task"] = asyncio.create_task(
            crash_timer(
                session
            )
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

    async def callback(
        self,
        interaction: discord.Interaction
    ):

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

        await interaction.response.send_modal(
            modal
        )


class StockSelectView(ui.View):

    def __init__(self, exchange):

        super().__init__(
            timeout=120
        )

        self.add_item(
            StockSelect(exchange)
        )


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

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        exchange = self.values[0]

        embed = discord.Embed(
            title=f"🏦 {exchange}",
            description="Chọn cổ phiếu muốn giao dịch."
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=StockSelectView(
                exchange
            )
        )


class ExchangeView(ui.View):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ExchangeSelect()
        )


# =========================================================
# !STOCK
# =========================================================

@bot.command()
async def stock(ctx):

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

    vnd = get_vnd(
        ctx.author.id
    )

    embed = discord.Embed(
        title="💰 SỐ DƯ",
        color=discord.Color.green()
    )

    embed.add_field(
        name="💵 VND",
        value=f"**{money(vnd)} VND**",
        inline=False
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# !PAY
# =========================================================

@bot.command()
async def pay(
    ctx,
    member: discord.Member,
    amount: str
):

    amount = parse_money(
        amount
    )

    if (
        amount is None
        or amount <= 0
    ):

        await ctx.send(
            "❌ Số tiền không hợp lệ."
        )

        return

    if member.id == ctx.author.id:

        await ctx.send(
            "❌ Không thể chuyển tiền cho chính mình."
        )

        return

    sender_money = get_vnd(
        ctx.author.id
    )

    if amount > sender_money:

        await ctx.send(
            f"❌ Bạn chỉ có **{money(sender_money)} VND**."
        )

        return

    add_vnd(
        ctx.author.id,
        -amount
    )

    add_vnd(
        member.id,
        amount
    )

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

    ensure_user(
        user_id
    )

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

            last_daily = datetime.fromisoformat(
                row[0]
            )

            cooldown = timedelta(
                hours=24
            )

            if now - last_daily < cooldown:

                remaining = (
                    cooldown
                    - (now - last_daily)
                )

                hours = int(
                    remaining.total_seconds()
                    // 3600
                )

                minutes = int(
                    (
                        remaining.total_seconds()
                        % 3600
                    )
                    // 60
                )

                await ctx.send(
                    f"⏳ Bạn đã nhận Daily rồi. "
                    f"Còn **{hours}h {minutes}m**."
                )

                return

        except ValueError:

            pass

    # Random 50k -> 500k
    reward = random.randint(
        50_000,
        500_000
    )

    add_vnd(
        user_id,
        reward
    )

    cursor.execute(
        """
        UPDATE users
        SET last_daily = ?
        WHERE user_id = ?
        """,
        (
            now.isoformat(),
            user_id
        )
    )

    db.commit()

    await ctx.send(
        f"🎁 Bạn nhận được "
        f"**{money(reward)} VND** từ Daily!"
    )


# =========================================================
# !DEPOSIT
# =========================================================

@bot.command()
async def deposit(
    ctx,
    amount: str
):

    amount = parse_money(
        amount
    )

    if (
        amount is None
        or amount <= 0
    ):

        await ctx.send(
            "❌ Số tiền không hợp lệ."
        )

        return

    await ctx.send(
        "⚠️ Deposit hiện chưa được kết nối với hệ thống ngân hàng."
    )


# =========================================================
# !WITHDRAW
# =========================================================

@bot.command()
async def withdraw(
    ctx,
    amount: str
):

    amount = parse_money(
        amount
    )

    if (
        amount is None
        or amount <= 0
    ):

        await ctx.send(
            "❌ Số tiền không hợp lệ."
        )

        return

    await ctx.send(
        "⚠️ Withdraw hiện chưa được kết nối với hệ thống ngân hàng."
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
        "`!balance` — Xem số dư\n"
        "`!pay @user <số tiền>` — Chuyển tiền\n"
        "`!daily` — Nhận Daily\n"
        "`!deposit <số tiền>` — Deposit\n"
        "`!withdraw <số tiền>` — Withdraw\n\n"
        "💡 Có thể nhập tiền dạng:\n"
        "`100k` `10m` `1b` `1t`"
    )

    await ctx.send(
        embed=embed
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

    await bot.process_commands(
        message
    )


# =========================================================
# RUN
# =========================================================

if not TOKEN:

    print(
        "❌ Chưa có DISCORD_TOKEN hoặc TOKEN."
    )

else:

    bot.run(
        TOKEN
    )
