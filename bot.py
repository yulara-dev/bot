import discord
from discord.ext import commands
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
    last_daily TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS exchange_cash (
    user_id INTEGER,
    exchange TEXT,
    vnd INTEGER DEFAULT 0,
    PRIMARY KEY(user_id, exchange)
)
""")

db.commit()


def ensure_user(user_id):
    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    if cursor.fetchone() is None:
        cursor.execute(
            """
            INSERT INTO users (user_id, vnd, usd, btc)
            VALUES (?, 0, 0, 0)
            """,
            (user_id,)
        )
        db.commit()


def get_vnd(user_id):
    ensure_user(user_id)

    cursor.execute(
        "SELECT vnd FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()

    return row[0] if row else 0


def add_vnd(user_id, amount):
    ensure_user(user_id)

    cursor.execute(
        """
        UPDATE users
        SET vnd = vnd + ?
        WHERE user_id = ?
        """,
        (amount, user_id)
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
        (amount, user_id)
    )

    db.commit()


def get_exchange_cash(user_id, exchange):
    cursor.execute(
        """
        SELECT vnd
        FROM exchange_cash
        WHERE user_id = ? AND exchange = ?
        """,
        (user_id, exchange)
    )

    row = cursor.fetchone()

    return row[0] if row else 0


def set_exchange_cash(user_id, exchange, amount):
    cursor.execute(
        """
        INSERT INTO exchange_cash (user_id, exchange, vnd)
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
# STOCK DATA
# =========================================================

STOCKS = {

    "NASDAQ": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("NVDA", "NVIDIA"),
        ("TSLA", "Tesla"),
        ("AMZN", "Amazon"),
        ("META", "Meta"),
    ],

    "NYSE": [
        ("JPM", "JPMorgan Chase"),
        ("KO", "Coca-Cola"),
        ("DIS", "Disney"),
        ("WMT", "Walmart"),
        ("V", "Visa"),
    ],

    "HOSE": [
        ("VIC", "Vingroup"),
        ("VHM", "Vinhomes"),
        ("FPT", "FPT"),
        ("HPG", "Hoa Phat"),
        ("VCB", "Vietcombank"),
    ],

    "TSE": [
        ("7203", "Toyota"),
        ("9984", "SoftBank"),
        ("6758", "Sony"),
    ],

    "HKEX": [
        ("0700", "Tencent"),
        ("9988", "Alibaba"),
        ("3690", "Meituan"),
    ],

    "HNX": [
        ("PVS", "PTSC"),
        ("SHS", "SHS"),
        ("CEO", "CEO Group"),
    ],

    "LSE": [
        ("SHEL", "Shell"),
        ("AZN", "AstraZeneca"),
        ("HSBA", "HSBC"),
    ],

    "SSE": [
        ("600519", "Kweichow Moutai"),
        ("601318", "Ping An"),
    ],

    "KRX": [
        ("005930", "Samsung Electronics"),
        ("000660", "SK Hynix"),
        ("035420", "NAVER"),
    ],

    "SGX": [
        ("D05", "DBS"),
        ("O39", "OCBC"),
        ("U11", "UOB"),
    ],

    "UPCoM": [
        ("ACV", "Airports Corporation"),
        ("VEA", "Vietnam Engine"),
    ],
}

EXCHANGES = list(STOCKS.keys())


# =========================================================
# ACTIVE SESSIONS
# =========================================================

sessions = {}


# =========================================================
# MONEY
# =========================================================

def money(amount):
    return f"{int(amount):,}".replace(",", ".")


# =========================================================
# RANDOM MOVEMENT
# =========================================================

def generate_movement(capital):

    if capital <= 0:
        return 0

    percent = random.uniform(
        -0.02,
        0.02
    )

    delta = int(
        capital * percent
    )

    if delta == 0:
        delta = random.choice([
            1000,
            2000,
            5000,
            10000,
            -1000,
            -2000,
            -5000,
            -10000
        ])

    return delta


# =========================================================
# EMBEDS
# =========================================================

def make_exchange_embed():

    return discord.Embed(
        title="🏦 Chọn sàn",
        description="Chọn sàn giao dịch bên dưới.",
        color=discord.Color.blurple()
    )


def make_stock_embed(
    exchange,
    symbol,
    company
):

    return discord.Embed(
        title="📈 Chọn cổ phiếu",
        description=(
            f"**Sàn:** `{exchange}`\n"
            f"**Cổ phiếu đang chọn:** `{symbol}`\n"
            f"**Công ty:** {company}\n\n"
            "Chọn cổ phiếu bên dưới."
        ),
        color=discord.Color.blurple()
    )


def make_capital_embed(
    exchange,
    symbol,
    company
):

    return discord.Embed(
        title="💰 Nhập số tiền vốn",
        description=(
            f"🏦 Sàn: **{exchange}**\n"
            f"📈 Cổ phiếu: **{symbol}**\n"
            f"🏢 Công ty: **{company}**\n\n"
            "Nhấn nút bên dưới để nhập số tiền vốn."
        ),
        color=discord.Color.gold()
    )


def make_market_embed(session):

    exchange = session["exchange"]
    symbol = session["symbol"]

    capital = session["capital"]
    delta = session["delta"]

    if delta >= 0:

        movement = (
            f"🟢 +{money(delta)} VND"
        )

    else:

        movement = (
            f"🔴 -{money(abs(delta))} VND"
        )

    embed = discord.Embed(
        title=f"📈 {exchange} • {symbol}",
        color=(
            discord.Color.green()
            if delta >= 0
            else discord.Color.red()
        )
    )

    embed.description = (
        f"💰 **Vốn:** {money(capital)} VND\n\n"
        f"**Biến động:**\n"
        f"{movement}"
    )

    return embed


def make_crash_embed(session):

    exchange = session["exchange"]
    symbol = session["symbol"]

    lost = session["crash_loss"]

    return discord.Embed(
        title="💥 SẬP SÀN!",
        description=(
            f"💵 **-{money(lost)} VND**\n\n"
            f"📉 **{exchange} • {symbol}**"
        ),
        color=discord.Color.red()
    )


# =========================================================
# EXCHANGE SELECT
# =========================================================

class ExchangeSelect(discord.ui.Select):

    def __init__(self, user_id):

        self.user_id = user_id

        options = [
            discord.SelectOption(
                label=exchange,
                value=exchange,
                emoji="🏦"
            )
            for exchange in EXCHANGES
        ]

        super().__init__(
            placeholder="🏦 Chọn sàn...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )

            return

        exchange = self.values[0]

        symbol, company = STOCKS[
            exchange
        ][0]

        await interaction.response.edit_message(
            embed=make_stock_embed(
                exchange,
                symbol,
                company
            ),
            view=StockSelectView(
                self.user_id,
                exchange
            )
        )


class ExchangeSelectView(discord.ui.View):

    def __init__(self, user_id):

        super().__init__(
            timeout=180
        )

        self.add_item(
            ExchangeSelect(
                user_id
            )
        )


# =========================================================
# STOCK SELECT
# =========================================================

class StockSelect(discord.ui.Select):

    def __init__(
        self,
        user_id,
        exchange
    ):

        self.user_id = user_id
        self.exchange = exchange

        options = [
            discord.SelectOption(
                label=symbol,
                description=company[:100],
                value=symbol,
                emoji="📈"
            )
            for symbol, company
            in STOCKS[exchange]
        ]

        super().__init__(
            placeholder="📈 Chọn cổ phiếu...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )

            return

        symbol = self.values[0]

        company = next(
            company
            for stock_symbol, company
            in STOCKS[self.exchange]
            if stock_symbol == symbol
        )

        await interaction.response.edit_message(
            embed=make_capital_embed(
                self.exchange,
                symbol,
                company
            ),
            view=CapitalView(
                self.user_id,
                self.exchange,
                symbol,
                company
            )
        )


class StockSelectView(discord.ui.View):

    def __init__(
        self,
        user_id,
        exchange
    ):

        super().__init__(
            timeout=180
        )

        self.add_item(
            StockSelect(
                user_id,
                exchange
            )
        )


# =========================================================
# CAPITAL VIEW
# =========================================================

class CapitalView(discord.ui.View):

    def __init__(
        self,
        user_id,
        exchange,
        symbol,
        company
    ):

        super().__init__(
            timeout=180
        )

        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.company = company

    async def interaction_check(
        self,
        interaction
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="💰 Nhập vốn",
        style=discord.ButtonStyle.primary
    )
    async def capital(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            CapitalModal(
                self.user_id,
                self.exchange,
                self.symbol,
                self.company
            )
        )


# =========================================================
# CAPITAL MODAL
# =========================================================

class CapitalModal(discord.ui.Modal):

    def __init__(
        self,
        user_id,
        exchange,
        symbol,
        company
    ):

        super().__init__(
            title="💰 Nhập số tiền vốn"
        )

        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.company = company

        self.amount = discord.ui.TextInput(
            label="Số tiền vốn (VND)",
            placeholder="Ví dụ: 10000000",
            required=True,
            min_length=1,
            max_length=20
        )

        self.add_item(
            self.amount
        )

    async def on_submit(
        self,
        interaction
    ):

        try:

            capital = int(
                self.amount.value
                .replace(".", "")
                .replace(",", "")
                .replace(" ", "")
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Số tiền không hợp lệ.",
                ephemeral=True
            )

            return

        if capital <= 0:

            await interaction.response.send_message(
                "❌ Số tiền phải lớn hơn 0.",
                ephemeral=True
            )

            return

        balance = get_vnd(
            self.user_id
        )

        if balance < capital:

            await interaction.response.send_message(
                (
                    "❌ Không đủ tiền.\n\n"
                    f"💰 Bạn có: **{money(balance)} VND**\n"
                    f"💵 Cần: **{money(capital)} VND**"
                ),
                ephemeral=True
            )

            return

        # Không cho tạo 2 phiên cùng lúc
        for old_session in sessions.values():

            if old_session["user_id"] == self.user_id:

                await interaction.response.send_message(
                    "❌ Bạn đang có một phiên giao dịch khác.",
                    ephemeral=True
                )

                return

        # Trừ tiền ví
        add_vnd(
            self.user_id,
            -capital
        )

        # Đưa tiền lên sàn
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

        market_view = MarketView(
            self.user_id
        )

        session["view"] = market_view

        # Đổi bảng cũ thành bảng thị trường
        await interaction.response.edit_message(
            embed=make_market_embed(
                session
            ),
            view=market_view
        )

        # Lấy message sau khi edit
        try:

            message = await interaction.original_response()

        except Exception:

            message = interaction.message

        session["message"] = message

        sessions[
            message.id
        ] = session

        # BẮT ĐẦU TỰ ĐỘNG CHẠY
        session["market_task"] = asyncio.create_task(
            market_loop(
                session
            )
        )

        # BẮT ĐẦU TIMER SẬP
        session["crash_task"] = asyncio.create_task(
            crash_timer(
                session
            )
        )


# =========================================================
# MARKET VIEW
# =========================================================

class MarketView(discord.ui.View):

    def __init__(self, user_id):

        super().__init__(
            timeout=None
        )

        self.user_id = user_id

    async def interaction_check(
        self,
        interaction
    ):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="💸 Take",
        style=discord.ButtonStyle.success,
        custom_id="stock_take"
    )
    async def take(
        self,
        interaction,
        button
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

        if session["crashed"]:

            await interaction.response.send_message(
                "💥 Sàn đã sập. Phiên giao dịch đã kết thúc.",
                ephemeral=True
            )

            return

        if session["ended"]:
            return

        session["ended"] = True

        # Dừng market loop
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

        exchange = session["exchange"]

        amount = get_exchange_cash(
            self.user_id,
            exchange
        )

        if amount <= 0:

            sessions.pop(
                message_id,
                None
            )

            await interaction.response.send_message(
                "❌ Không còn tiền trên sàn.",
                ephemeral=True
            )

            return

        # Xóa tiền trên sàn
        set_exchange_cash(
            self.user_id,
            exchange,
            0
        )

        # Trả về ví
        add_vnd(
            self.user_id,
            amount
        )

        # Xóa session
        sessions.pop(
            message_id,
            None
        )

        embed = discord.Embed(
            title="💸 Take thành công",
            description=(
                f"🏦 Sàn: **{exchange}**\n\n"
                f"💰 Đã lấy: **{money(amount)} VND**"
            ),
            color=discord.Color.green()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=None
        )


# =========================================================
# MARKET LOOP
# MỖI 1 GIÂY
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

            # Random biến động
            delta = generate_movement(
                current_money
            )

            new_money = max(
                0,
                current_money + delta
            )

            # Lưu tiền mới
            set_exchange_cash(
                user_id,
                exchange,
                new_money
            )

            # Cập nhật session
            session["capital"] = new_money
            session["delta"] = delta

            message = session.get(
                "message"
            )

            if message is None:
                continue

            try:

                await message.edit(
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

        # Random 30-60 giây
        delay = random.randint(
            30,
            60
        )

        print(
            f"⏱️ {session['exchange']} "
            f"{session['symbol']} "
            f"sẽ được kiểm tra crash sau "
            f"{delay}s"
        )

        await asyncio.sleep(
            delay
        )

        if (
            session["ended"]
            or session["crashed"]
        ):
            return

        user_id = session["user_id"]
        exchange = session["exchange"]

        current_money = get_exchange_cash(
            user_id,
            exchange
        )

        if current_money <= 0:
            return

        # Mất 40%-100%
        loss_percent = random.uniform(
            0.40,
            1.00
        )

        loss = int(
            current_money * loss_percent
        )

        if loss <= 0:
            loss = current_money

        remaining = max(
            0,
            current_money - loss
        )

        # Lưu tiền sau crash
        set_exchange_cash(
            user_id,
            exchange,
            remaining
        )

        session["crashed"] = True
        session["ended"] = True
        session["crash_loss"] = loss
        session["capital"] = remaining

        # Dừng market
        market_task = session.get(
            "market_task"
        )

        if (
            market_task
            and not market_task.done()
        ):

            market_task.cancel()

        message = session.get(
            "message"
        )

        if message is None:
            return

        try:

            await message.edit(
                embed=make_crash_embed(
                    session
                ),
                view=None
            )

            print(
                f"💥 SẬP SÀN: "
                f"{exchange} • {session['symbol']} "
                f"-{money(loss)} VND"
            )

        except discord.NotFound:
            pass

        except discord.HTTPException as e:

            print(
                f"⚠️ Crash edit error: {e}"
            )

        # Xóa session
        sessions.pop(
            message.id,
            None
        )

    except asyncio.CancelledError:

        return

    except Exception as e:

        print(
            f"❌ CRASH TIMER ERROR: "
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# !STOCK
# =========================================================

@bot.command(
    name="stock"
)
async def stock(ctx):

    ensure_user(
        ctx.author.id
    )

    await ctx.send(
        embed=make_exchange_embed(),
        view=ExchangeSelectView(
            ctx.author.id
        )
    )


# =========================================================
# !BALANCE
# =========================================================

@bot.command(
    name="balance"
)
async def balance(ctx):

    ensure_user(
        ctx.author.id
    )

    vnd = get_vnd(
        ctx.author.id
    )

    embed = discord.Embed(
        title="💰 Ví tiền",
        description=(
            f"💵 VND: **{money(vnd)} VND**\n"
            f"💲 USD: **0 USD**\n"
            f"₿ BTC: **0 BTC**"
        ),
        color=discord.Color.gold()
    )

    await ctx.send(
        embed=embed
    )


# =========================================================
# !PAY
# =========================================================

@bot.command(
    name="pay"
)
async def pay(
    ctx,
    member: discord.Member = None,
    amount: int = None
):

    if member is None or amount is None:

        await ctx.send(
            "❌ Dùng: `!pay @người amount`"
        )

        return

    if member.id == ctx.author.id:

        await ctx.send(
            "❌ Không thể tự pay cho chính mình."
        )

        return

    if amount <= 0:

        await ctx.send(
            "❌ Số tiền phải lớn hơn 0."
        )

        return

    sender_balance = get_vnd(
        ctx.author.id
    )

    if sender_balance < amount:

        await ctx.send(
            (
                "❌ Không đủ tiền.\n"
                f"💰 Bạn có: "
                f"**{money(sender_balance)} VND**"
            )
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
        (
            f"💸 **{ctx.author.display_name}** "
            f"đã pay **{money(amount)} VND** "
            f"cho **{member.display_name}**."
        )
    )


# =========================================================
# !DAILY
# =========================================================

@bot.command(
    name="daily"
)
async def daily(ctx):

    ensure_user(
        ctx.author.id
    )

    cursor.execute(
        """
        SELECT last_daily
        FROM users
        WHERE user_id = ?
        """,
        (ctx.author.id,)
    )

    row = cursor.fetchone()

    now = datetime.now()

    if row and row[0]:

        try:

            last = datetime.fromisoformat(
                row[0]
            )

            if now - last < timedelta(
                hours=24
            ):

                remaining = (
                    timedelta(hours=24)
                    - (now - last)
                )

                hours = int(
                    remaining.total_seconds()
                    // 3600
                )

                minutes = int(
                    (
                        remaining.total_seconds()
                        % 3600
                    ) // 60
                )

                await ctx.send(
                    (
                        "⏳ Bạn đã nhận Daily rồi.\n"
                        f"Thử lại sau "
                        f"**{hours}h {minutes}m**."
                    )
                )

                return

        except Exception:
            pass

    reward = 100000

    add_vnd(
        ctx.author.id,
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
            ctx.author.id
        )
    )

    db.commit()

    await ctx.send(
        (
            "🎁 **Daily thành công!**\n"
            f"💰 Nhận được "
            f"**{money(reward)} VND**."
        )
    )


# =========================================================
# ON READY
# =========================================================

@bot.event
async def on_ready():

    print("=" * 40)

    print(
        f"✅ Đăng nhập thành công: {bot.user}"
    )

    print(
        f"🆔 Bot ID: {bot.user.id}"
    )

    print(
        "📈 STOCK LIVE UPDATE: ON"
    )

    print("=" * 40)


# =========================================================
# MESSAGE
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    print(
        f"📩 {message.author}: "
        f"{message.content}"
    )

    await bot.process_commands(
        message
    )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:

    print(
        "❌ Chưa có DISCORD_TOKEN hoặc TOKEN."
    )

else:

    bot.run(
        TOKEN
    )
