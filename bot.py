import os
import random
import sqlite3
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")

PREFIX = "!"

DB_FILE = "stock_bot.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    vnd INTEGER NOT NULL DEFAULT 0,
    usd REAL NOT NULL DEFAULT 0,
    btc REAL NOT NULL DEFAULT 0,
    last_daily TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS exchange_cash (
    user_id INTEGER NOT NULL,
    exchange TEXT NOT NULL,
    vnd INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, exchange)
)
""")

db.commit()


def ensure_user(user_id):
    db.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    db.commit()


def get_user(user_id):
    ensure_user(user_id)
    return db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()


def get_exchange_cash(user_id, exchange):
    row = db.execute("""
        SELECT vnd
        FROM exchange_cash
        WHERE user_id = ? AND exchange = ?
    """, (user_id, exchange)).fetchone()

    return row["vnd"] if row else 0


def add_exchange_cash(user_id, exchange, amount):
    current = get_exchange_cash(user_id, exchange)

    db.execute("""
        INSERT INTO exchange_cash (user_id, exchange, vnd)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, exchange)
        DO UPDATE SET vnd = excluded.vnd
    """, (
        user_id,
        exchange,
        current + amount
    ))

    db.commit()


def set_exchange_cash(user_id, exchange, amount):
    db.execute("""
        INSERT INTO exchange_cash (user_id, exchange, vnd)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, exchange)
        DO UPDATE SET vnd = excluded.vnd
    """, (
        user_id,
        exchange,
        max(0, int(amount))
    ))

    db.commit()


def fmt_money(amount):
    return f"{int(amount):,}".replace(",", ".")


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
# ACTIVE STOCK SESSIONS
# =========================================================

sessions = {}


# =========================================================
# EMBEDS
# =========================================================

def make_exchange_embed(exchange, index):
    embed = discord.Embed(
        title="🏦 Chọn sàn",
        description=(
            f"**{exchange}**\n\n"
            f"Sàn {index + 1}/{len(EXCHANGES)}\n\n"
            "⬆️ / ⬇️ để đổi sàn\n"
            "✅ Bấm **Chọn sàn** để tiếp tục"
        ),
        color=discord.Color.blurple()
    )

    return embed


def make_stock_embed(exchange, symbol, company, index):
    stock_list = STOCKS[exchange]

    embed = discord.Embed(
        title="📈 Chọn cổ phiếu",
        description=(
            f"**{symbol} — {company}**\n\n"
            f"Sàn: **{exchange}**\n"
            f"Cổ phiếu {index + 1}/{len(stock_list)}\n\n"
            "⬆️ / ⬇️ để đổi cổ phiếu\n"
            "✅ Bấm **Chọn cổ phiếu** để tiếp tục"
        ),
        color=discord.Color.blurple()
    )

    return embed


def make_capital_embed(exchange, symbol, company):
    embed = discord.Embed(
        title="💰 Nhập số tiền vốn",
        description=(
            f"🏦 Sàn: **{exchange}**\n"
            f"📈 Cổ phiếu: **{symbol} — {company}**\n\n"
            "Bấm nút bên dưới và nhập số tiền VND muốn đưa vào sàn."
        ),
        color=discord.Color.gold()
    )

    return embed


def make_market_embed(session):
    capital = session["capital"]
    delta = session["delta"]

    if delta >= 0:
        color = discord.Color.green()
        movement = (
            "```ansi\n"
            f"\u001b[2;32m+{fmt_money(delta)} VND\u001b[0m\n"
            "```"
        )
    else:
        color = discord.Color.red()
        movement = (
            "```ansi\n"
            f"\u001b[2;31m-{fmt_money(abs(delta))} VND\u001b[0m\n"
            "```"
        )

    embed = discord.Embed(
        title=f"📈 {session['exchange']} • {session['symbol']}",
        description=(
            f"💰 **Vốn: {fmt_money(capital)} VND**\n\n"
            f"Biến động:\n{movement}"
        ),
        color=color
    )

    return embed


def make_crash_embed(session, loss):
    embed = discord.Embed(
        title="💥 SẬP SÀN!",
        description=(
            f"💵 **-{fmt_money(loss)} VND**\n"
            f"📉 **{session['exchange']} • {session['symbol']}**"
        ),
        color=discord.Color.red()
    )

    return embed


# =========================================================
# EXCHANGE SELECT
# =========================================================

class ExchangeView(discord.ui.View):

    def __init__(self, user_id, index=0):
        super().__init__(timeout=180)

        self.user_id = user_id
        self.index = index

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="⬆️",
        style=discord.ButtonStyle.secondary
    )
    async def up(self, interaction, button):

        self.index = (self.index - 1) % len(EXCHANGES)

        await interaction.response.edit_message(
            embed=make_exchange_embed(
                EXCHANGES[self.index],
                self.index
            ),
            view=self
        )

    @discord.ui.button(
        label="🏦 Chọn sàn",
        style=discord.ButtonStyle.primary
    )
    async def choose(self, interaction, button):

        exchange = EXCHANGES[self.index]

        view = StockView(
            self.user_id,
            exchange,
            0
        )

        symbol, company = STOCKS[exchange][0]

        await interaction.response.edit_message(
            embed=make_stock_embed(
                exchange,
                symbol,
                company,
                0
            ),
            view=view
        )

    @discord.ui.button(
        label="⬇️",
        style=discord.ButtonStyle.secondary
    )
    async def down(self, interaction, button):

        self.index = (self.index + 1) % len(EXCHANGES)

        await interaction.response.edit_message(
            embed=make_exchange_embed(
                EXCHANGES[self.index],
                self.index
            ),
            view=self
        )


# =========================================================
# STOCK SELECT
# =========================================================

class StockView(discord.ui.View):

    def __init__(self, user_id, exchange, index=0):
        super().__init__(timeout=180)

        self.user_id = user_id
        self.exchange = exchange
        self.index = index

    async def interaction_check(self, interaction):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="⬆️",
        style=discord.ButtonStyle.secondary
    )
    async def up(self, interaction, button):

        self.index = (
            self.index - 1
        ) % len(STOCKS[self.exchange])

        symbol, company = STOCKS[self.exchange][self.index]

        await interaction.response.edit_message(
            embed=make_stock_embed(
                self.exchange,
                symbol,
                company,
                self.index
            ),
            view=self
        )

    @discord.ui.button(
        label="📈 Chọn cổ phiếu",
        style=discord.ButtonStyle.primary
    )
    async def choose(self, interaction, button):

        symbol, company = STOCKS[self.exchange][self.index]

        view = CapitalView(
            self.user_id,
            self.exchange,
            symbol,
            company
        )

        await interaction.response.edit_message(
            embed=make_capital_embed(
                self.exchange,
                symbol,
                company
            ),
            view=view
        )

    @discord.ui.button(
        label="⬇️",
        style=discord.ButtonStyle.secondary
    )
    async def down(self, interaction, button):

        self.index = (
            self.index + 1
        ) % len(STOCKS[self.exchange])

        symbol, company = STOCKS[self.exchange][self.index]

        await interaction.response.edit_message(
            embed=make_stock_embed(
                self.exchange,
                symbol,
                company,
                self.index
            ),
            view=self
        )


# =========================================================
# CAPITAL MODAL
# =========================================================

class CapitalModal(discord.ui.Modal, title="💰 Nhập số tiền vốn"):

    amount = discord.ui.TextInput(
        label="Số tiền vốn (VND)",
        placeholder="Ví dụ: 10000000",
        required=True,
        min_length=1,
        max_length=20
    )

    def __init__(
        self,
        user_id,
        exchange,
        symbol,
        company
    ):
        super().__init__()

        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.company = company

    async def on_submit(self, interaction):

        try:
            amount = int(
                str(self.amount.value)
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

        if amount <= 0:

            await interaction.response.send_message(
                "❌ Số tiền phải lớn hơn 0.",
                ephemeral=True
            )
            return

        user = get_user(self.user_id)

        if user["vnd"] < amount:

            await interaction.response.send_message(
                (
                    "❌ Không đủ tiền.\n"
                    f"💵 Bạn có: **{fmt_money(user['vnd'])} VND**"
                ),
                ephemeral=True
            )
            return

        # Trừ tiền trong ví
        db.execute(
            "UPDATE users SET vnd = vnd - ? WHERE user_id = ?",
            (amount, self.user_id)
        )
        db.commit()

        # Đưa tiền vào sàn
        add_exchange_cash(
            self.user_id,
            self.exchange,
            amount
        )

        session = {
            "user_id": self.user_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "company": self.company,
            "capital": amount,
            "delta": 0,
            "crashed": False,
        }

        # Tạo key tạm thời bằng message ID
        message_id = interaction.message.id

        sessions[message_id] = session

        await interaction.response.edit_message(
            embed=make_market_embed(session),
            view=MarketView(self.user_id)
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
        super().__init__(timeout=180)

        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.company = company

    async def interaction_check(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng của bạn.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="💰 Nhập số tiền vốn",
        style=discord.ButtonStyle.success
    )
    async def capital(self, interaction, button):

        await interaction.response.send_modal(
            CapitalModal(
                self.user_id,
                self.exchange,
                self.symbol,
                self.company
            )
        )


# =========================================================
# PAY MODAL
# =========================================================

class PayModal(discord.ui.Modal, title="💸 Pay"):

    user_id_input = discord.ui.TextInput(
        label="ID người nhận",
        placeholder="Ví dụ: 123456789012345678",
        required=True
    )

    amount_input = discord.ui.TextInput(
        label="Số tiền VND",
        placeholder="Ví dụ: 10000",
        required=True
    )

    async def on_submit(self, interaction):

        try:
            receiver_id = int(
                str(self.user_id_input.value).strip()
            )

            amount = int(
                str(self.amount_input.value)
                .replace(".", "")
                .replace(",", "")
                .replace(" ", "")
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ ID hoặc số tiền không hợp lệ.",
                ephemeral=True
            )
            return

        if amount <= 0:

            await interaction.response.send_message(
                "❌ Số tiền phải lớn hơn 0.",
                ephemeral=True
            )
            return

        if receiver_id == interaction.user.id:

            await interaction.response.send_message(
                "❌ Không thể Pay cho chính mình.",
                ephemeral=True
            )
            return

        sender = get_user(interaction.user.id)

        if sender["vnd"] < amount:

            await interaction.response.send_message(
                (
                    "❌ Bạn không đủ tiền.\n"
                    f"💵 Số dư: **{fmt_money(sender['vnd'])} VND**"
                ),
                ephemeral=True
            )
            return

        ensure_user(receiver_id)

        db.execute(
            "UPDATE users SET vnd = vnd - ? WHERE user_id = ?",
            (amount, interaction.user.id)
        )

        db.execute(
            "UPDATE users SET vnd = vnd + ? WHERE user_id = ?",
            (amount, receiver_id)
        )

        db.commit()

        await interaction.response.send_message(
            (
                "✅ **Pay thành công!**\n\n"
                f"💸 Đã chuyển **{fmt_money(amount)} VND**\n"
                f"👤 Người nhận: <@{receiver_id}>"
            ),
            ephemeral=True
        )


# =========================================================
# MARKET VIEW
# =========================================================

class MarketView(discord.ui.View):

    def __init__(self, user_id):
        super().__init__(timeout=None)

        self.user_id = user_id

    async def interaction_check(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "❌ Đây không phải bảng đầu tư của bạn.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="💸 Pay",
        style=discord.ButtonStyle.primary
    )
    async def pay(self, interaction, button):

        await interaction.response.send_modal(
            PayModal()
        )


# =========================================================
# !STOCK
# =========================================================

@bot.command(name="stock")
async def stock(ctx):

    ensure_user(ctx.author.id)

    view = ExchangeView(
        ctx.author.id,
        0
    )

    await ctx.send(
        embed=make_exchange_embed(
            EXCHANGES[0],
            0
        ),
        view=view
    )


# =========================================================
# !BALANCE
# =========================================================

@bot.command(name="balance", aliases=["bal"])
async def balance(ctx):

    user = get_user(ctx.author.id)

    rows = db.execute("""
        SELECT exchange, vnd
        FROM exchange_cash
        WHERE user_id = ? AND vnd > 0
        ORDER BY exchange
    """, (ctx.author.id,)).fetchall()

    exchange_text = ""

    if rows:

        for row in rows:

            exchange_text += (
                f"🏦 {row['exchange']}: "
                f"**{fmt_money(row['vnd'])} VND**\n"
            )

    else:
        exchange_text = "Không có tiền đang nằm trên sàn."

    embed = discord.Embed(
        title=f"💰 Ví của {ctx.author.display_name}",
        color=discord.Color.green()
    )

    embed.add_field(
        name="💵 VND",
        value=f"**{fmt_money(user['vnd'])} VND**",
        inline=False
    )

    embed.add_field(
        name="💲 USD",
        value=f"**{user['usd']:,.2f} USD**",
        inline=False
    )

    embed.add_field(
        name="₿ BTC",
        value=f"**{user['btc']:.8f} BTC**",
        inline=False
    )

    embed.add_field(
        name="🏦 Tiền đang nạp vào sàn",
        value=exchange_text,
        inline=False
    )

    await ctx.send(embed=embed)


# =========================================================
# !DAILY
# =========================================================

@bot.command(name="daily")
async def daily(ctx):

    user = get_user(ctx.author.id)

    now = datetime.utcnow()

    if user["last_daily"]:

        try:
            last = datetime.fromisoformat(
                user["last_daily"]
            )

            next_time = last + timedelta(days=1)

            if now < next_time:

                remaining = next_time - now

                hours = int(
                    remaining.total_seconds() // 3600
                )

                minutes = int(
                    (remaining.total_seconds() % 3600) // 60
                )

                await ctx.send(
                    (
                        "⏳ Bạn đã nhận Daily rồi.\n"
                        f"Thử lại sau **{hours} giờ {minutes} phút**."
                    )
                )

                return

        except ValueError:
            pass

    reward = random.randint(
        10000,
        30000
    )

    db.execute("""
        UPDATE users
        SET vnd = vnd + ?, last_daily = ?
        WHERE user_id = ?
    """, (
        reward,
        now.isoformat(),
        ctx.author.id
    ))

    db.commit()

    await ctx.send(
        (
            "🎁 **Daily!**\n\n"
            f"💵 Bạn nhận được **{fmt_money(reward)} VND**"
        )
    )


# =========================================================
# !PAY
# =========================================================

@bot.command(name="pay")
async def pay(ctx, member: discord.Member = None, amount: int = None):

    if member is None or amount is None:

        await ctx.send(
            "❌ Dùng: `!pay @nguoichoi <so_tien>`"
        )

        return

    if member.id == ctx.author.id:

        await ctx.send(
            "❌ Không thể Pay cho chính mình."
        )

        return

    if amount <= 0:

        await ctx.send(
            "❌ Số tiền phải lớn hơn 0."
        )

        return

    sender = get_user(ctx.author.id)

    if sender["vnd"] < amount:

        await ctx.send(
            (
                "❌ Không đủ tiền.\n"
                f"💵 Số dư: **{fmt_money(sender['vnd'])} VND**"
            )
        )

        return

    ensure_user(member.id)

    db.execute(
        "UPDATE users SET vnd = vnd - ? WHERE user_id = ?",
        (amount, ctx.author.id)
    )

    db.execute(
        "UPDATE users SET vnd = vnd + ? WHERE user_id = ?",
        (amount, member.id)
    )

    db.commit()

    await ctx.send(
        (
            "✅ **Pay thành công!**\n\n"
            f"💸 **{fmt_money(amount)} VND**\n"
            f"👤 Người nhận: {member.mention}"
        )
    )


# =========================================================
# !DEPOSIT
# =========================================================

@bot.command(name="deposit")
async def deposit(ctx, exchange: str = None, amount: int = None):

    if exchange is None or amount is None:

        await ctx.send(
            "❌ Dùng: `!deposit NASDAQ 1000000`"
        )

        return

    exchange = exchange.upper()

    if exchange not in EXCHANGES:

        await ctx.send(
            "❌ Sàn không tồn tại."
        )

        return

    if amount <= 0:

        await ctx.send(
            "❌ Số tiền phải lớn hơn 0."
        )

        return

    user = get_user(ctx.author.id)

    if user["vnd"] < amount:

        await ctx.send(
            (
                "❌ Không đủ VND.\n"
                f"💵 Bạn có: **{fmt_money(user['vnd'])} VND**"
            )
        )

        return

    db.execute(
        "UPDATE users SET vnd = vnd - ? WHERE user_id = ?",
        (amount, ctx.author.id)
    )

    db.commit()

    add_exchange_cash(
        ctx.author.id,
        exchange,
        amount
    )

    await ctx.send(
        (
            "✅ **Nạp tiền vào sàn thành công!**\n\n"
            f"🏦 Sàn: **{exchange}**\n"
            f"💵 Nạp: **{fmt_money(amount)} VND**"
        )
    )


# =========================================================
# !WITHDRAW
# =========================================================

@bot.command(name="withdraw")
async def withdraw(ctx, exchange: str = None, amount: int = None):

    if exchange is None or amount is None:

        await ctx.send(
            "❌ Dùng: `!withdraw NASDAQ 1000000`"
        )

        return

    exchange = exchange.upper()

    if exchange not in EXCHANGES:

        await ctx.send(
            "❌ Sàn không tồn tại."
        )

        return

    if amount <= 0:

        await ctx.send(
            "❌ Số tiền phải lớn hơn 0."
        )

        return

    cash = get_exchange_cash(
        ctx.author.id,
        exchange
    )

    if cash < amount:

        await ctx.send(
            (
                "❌ Không đủ tiền trên sàn.\n"
                f"🏦 Đang có: **{fmt_money(cash)} VND**"
            )
        )

        return

    set_exchange_cash(
        ctx.author.id,
        exchange,
        cash - amount
    )

    db.execute(
        "UPDATE users SET vnd = vnd + ? WHERE user_id = ?",
        (amount, ctx.author.id)
    )

    db.commit()

    await ctx.send(
        (
            "✅ **Rút tiền khỏi sàn thành công!**\n\n"
            f"🏦 Sàn: **{exchange}**\n"
            f"💵 Rút: **{fmt_money(amount)} VND**"
        )
    )


# =========================================================
# MARKET UPDATE
# =========================================================

@tasks.loop(seconds=8)
async def market_update():

    for message_id, session in list(sessions.items()):

        if session["crashed"]:
            continue

        capital = session["capital"]

        # Biến động từ -6% đến +6% vốn
        session["delta"] = int(
            capital * random.uniform(
                -0.06,
                0.06
            )
        )

        try:

            channel = bot.get_channel(
                getattr(
                    session.get("channel"),
                    "id",
                    0
                )
            )

            # Nếu không lưu channel thì tìm message bằng cache
            message = None

            for channel_obj in bot.get_all_channels():

                if not hasattr(channel_obj, "fetch_message"):
                    continue

                try:

                    message = await channel_obj.fetch_message(
                        message_id
                    )

                    if message:
                        break

                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException
                ):
                    continue

            if message is None:
                continue

            await message.edit(
                embed=make_market_embed(session),
                view=MarketView(session["user_id"])
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            pass


# =========================================================
# RANDOM CRASH
# =========================================================

@tasks.loop(seconds=60)
async def random_crash():

    active = [
        (message_id, session)
        for message_id, session in sessions.items()
        if not session["crashed"]
    ]

    if not active:
        return

    # Random thời điểm sập.
    # Mỗi phút có 4% khả năng xảy ra.
    if random.random() > 0.04:
        return

    message_id, session = random.choice(active)

    exchange = session["exchange"]

    # Tất cả người đang có tiền trên sàn này
    rows = db.execute("""
        SELECT user_id, vnd
        FROM exchange_cash
        WHERE exchange = ? AND vnd > 0
    """, (exchange,)).fetchall()

    losses = {}

    for row in rows:

        balance = int(row["vnd"])

        # Mất ngẫu nhiên 40% - 100%
        loss_percent = random.uniform(
            0.40,
            1.00
        )

        loss = int(
            balance * loss_percent
        )

        loss = max(
            0,
            min(loss, balance)
        )

        if loss > 0:

            set_exchange_cash(
                row["user_id"],
                exchange,
                balance - loss
            )

            losses[row["user_id"]] = loss

    # Tìm số tiền người đang xem bảng bị mất
    user_loss = losses.get(
        session["user_id"],
        0
    )

    # Nếu không có tiền trong DB vì lý do nào đó,
    # dùng vốn của session làm giới hạn.
    user_loss = min(
        user_loss,
        session["capital"]
    )

    session["crashed"] = True
    session["delta"] = -user_loss

    # Tìm message
    message = None

    for channel in bot.get_all_channels():

        if not hasattr(channel, "fetch_message"):
            continue

        try:

            message = await channel.fetch_message(
                message_id
            )

            if message:
                break

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            continue

    if message is not None:

        try:

            await message.edit(
                embed=make_crash_embed(
                    session,
                    user_loss
                ),
                view=None
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ):
            pass


# =========================================================
# STARTUP
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ Đăng nhập thành công: "
        f"{bot.user} ({bot.user.id})"
    )

    print(
        "📈 Stock Bot đang chạy."
    )

    if not market_update.is_running():
        market_update.start()

    if not random_crash.is_running():
        random_crash.start()


# =========================================================
# ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ Không tìm thấy người chơi."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ Thiếu thông tin. Kiểm tra lại lệnh."
        )

        return

    print(
        "Command error:",
        repr(error)
    )


# =========================================================
# RUN
# =========================================================

if not TOKEN:

    print(
        "❌ Chưa có TOKEN."
    )

    print(
        "Hãy đặt biến môi trường TOKEN hoặc DISCORD_TOKEN."
    )

else:

    bot.run(TOKEN)
