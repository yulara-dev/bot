import discord
from discord.ext import commands, tasks
import sqlite3, random, time, os

TOKEN = os.getenv("TOKEN", "").strip()

print("TOKEN EXISTS:", bool(TOKEN))
print("TOKEN LENGTH:", len(TOKEN))
print("TOKEN START:", TOKEN[:5])
db = sqlite3.connect('stockbot.db')
cur = db.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, vnd REAL DEFAULT 0, usd REAL DEFAULT 0, btc REAL DEFAULT 0, last_daily INTEGER DEFAULT 0)')
cur.execute('CREATE TABLE IF NOT EXISTS stocks (symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, price REAL)')
cur.execute('CREATE TABLE IF NOT EXISTS holdings (user_id INTEGER, symbol TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY(user_id,symbol))')
STOCKS=[('AAPL','Apple','NASDAQ',150),('MSFT','Microsoft','NASDAQ',420),('NVDA','NVIDIA','NASDAQ',180),('TSLA','Tesla','NASDAQ',350),('JPM','JPMorgan Chase','NYSE',220),('VIC','Vingroup','HOSE',45000),('VHM','Vinhomes','HOSE',52000),('FPT','FPT','HOSE',135000),('HPG','Hoa Phat','HOSE',28000),('VCB','Vietcombank','HOSE',95000),('7203','Toyota','TSE',2800),('9984','SoftBank','TSE',8500),('0700','Tencent','HKEX',520)]
for s in STOCKS: cur.execute('INSERT OR IGNORE INTO stocks VALUES (?,?,?,?)',s)
db.commit()

# Lưu giá trước đó để hiển thị tăng/giảm.
price_history = {}
last_crash_info = "Chưa có lần sập sàn nào."

# Reset existing accounts once so the old 10,000,000 VND starting balance is removed.
if db.execute('PRAGMA user_version').fetchone()[0] < 1:
    cur.execute('UPDATE users SET vnd=0, usd=0, btc=0')
    db.execute('PRAGMA user_version = 1')
    db.commit()

intents=discord.Intents.default(); intents.message_content=True; bot=commands.Bot(command_prefix='!', intents=intents)

def user(uid):
    cur.execute('SELECT * FROM users WHERE user_id=?',(uid,)); r=cur.fetchone()
    if not r:
        cur.execute('INSERT INTO users(user_id, vnd, usd, btc) VALUES(?, 0, 0, 0)',(uid,)); db.commit(); cur.execute('SELECT * FROM users WHERE user_id=?',(uid,)); r=cur.fetchone()
    return r

def stock(sym):
    cur.execute('SELECT symbol,name,exchange,price FROM stocks WHERE symbol=?',(sym.upper(),)); return cur.fetchone()

def fmt(x): return f'{x:,.0f}'


EXCHANGES = ["NYSE", "NASDAQ", "HOSE", "HNX", "TSE", "HKEX", "LSE", "SSE", "KRX", "SGX", "UPCoM"]

class InvestMoneyModal(discord.ui.Modal, title="💰 NHẬP TIỀN ĐẦU TƯ"):
    money = discord.ui.TextInput(
        label="Số tiền VND",
        placeholder="VD: 100000",
        required=True,
        max_length=15
    )

    def __init__(self, exchange, symbol):
        super().__init__()
        self.exchange = exchange
        self.symbol = symbol

    async def on_submit(self, i):
        try:
            money = int(self.money.value.replace(",", "").replace(".", "").strip())
            if money <= 0:
                raise ValueError
        except ValueError:
            await i.response.send_message("❌ Số tiền không hợp lệ.", ephemeral=True)
            return

        st = stock(self.symbol)
        if not st or st[2] != self.exchange:
            await i.response.send_message("❌ Cổ phiếu không hợp lệ.", ephemeral=True)
            return

        u = user(i.user.id)
        if u[1] < money:
            await i.response.send_message(
                f"❌ Không đủ tiền. Bạn có **{fmt(u[1])} VND**.",
                ephemeral=True
            )
            return

        # Buy whole shares using the entered amount.
        amount = int(money // st[3])
        if amount < 1:
            await i.response.send_message(
                f"❌ Số tiền quá ít. Giá 1 {self.symbol} hiện là **{fmt(st[3])} VND**.",
                ephemeral=True
            )
            return

        total = st[3] * amount
        cur.execute(
            "UPDATE users SET vnd=vnd-? WHERE user_id=?",
            (total, i.user.id)
        )
        cur.execute(
            "INSERT INTO holdings VALUES(?,?,?) "
            "ON CONFLICT(user_id,symbol) DO UPDATE SET amount=amount+excluded.amount",
            (i.user.id, self.symbol, amount)
        )
        db.commit()

        await i.response.send_message(
            f"✅ Đã đầu tư **{fmt(total)} VND** vào **{self.symbol}** "
            f"trên **{self.exchange}**.\n"
            f"📦 Nhận được **{amount} cổ phiếu**.\n"
            f"💵 Tiền dư: **{fmt(money-total)} VND**.",
            ephemeral=True
        )


class ExchangeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=e, value=e, description=f"Chọn sàn {e}")
            for e in EXCHANGES
        ]
        super().__init__(
            placeholder="🏦 Chọn sàn chứng khoán...",
            options=options,
            custom_id="exchange_select"
        )

    async def callback(self, i):
        view = self.view
        view.exchange = self.values[0]
        view.symbol = None
        if view.stock_select is not None:
            view.remove_item(view.stock_select)
        view.stock_select = StockSelect(view.exchange)
        view.add_item(view.stock_select)
        await i.response.edit_message(embed=view.make_embed(), view=view)


class StockSelect(discord.ui.Select):
    def __init__(self, exchange):
        rows = []
        cur.execute(
            "SELECT symbol,name,price FROM stocks WHERE exchange=? ORDER BY symbol",
            (exchange,)
        )
        rows = cur.fetchall()

        options = [
            discord.SelectOption(
                label=f"{s} — {n}"[:100],
                value=s,
                description=f"Giá: {p:,.2f} VND"[:100]
            )
            for s, n, p in rows
        ]

        if not options:
            options = [discord.SelectOption(
                label="Chưa có cổ phiếu",
                value="none"
            )]

        super().__init__(
            placeholder=f"📈 Chọn cổ phiếu trên {exchange}...",
            options=options[:25],
            custom_id=f"stock_select_{exchange}"
        )

    async def callback(self, i):
        view = self.view
        self_symbol = self.values[0]
        if self_symbol == "none":
            await i.response.send_message("❌ Sàn này chưa có mã cổ phiếu.", ephemeral=True)
            return
        view.symbol = self_symbol
        await i.response.edit_message(embed=view.make_embed(), view=view)


class StockTradeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.exchange = None
        self.symbol = None
        self.stock_select = None
        self.add_item(ExchangeSelect())

    def make_embed(self):
        if not self.exchange:
            return discord.Embed(
                title="📈 CHỌN SÀN CHỨNG KHOÁN",
                description="Dùng ô **🏦 Chọn sàn** bên dưới để chọn sàn.\n"
                            "Sau đó chọn mã cổ phiếu rồi nhập số tiền muốn đầu tư.",
                color=discord.Color.blurple()
            )

        text = f"🏦 Sàn: **{self.exchange}**\n"
        if self.symbol:
            st = stock(self.symbol)
            if st:
                text += (
                    f"📊 Mã: **{st[0]} — {st[1]}**\n"
                    f"💰 Giá hiện tại: **{fmt(st[3])} VND**\n\n"
                    "➡️ Bấm **💰 Nhập tiền** để nhập số VND muốn đầu tư."
                )
        else:
            text += "📊 Hãy chọn một mã cổ phiếu ở ô bên dưới."

        return discord.Embed(
            title="📈 GIAO DỊCH CHỨNG KHOÁN",
            description=text,
            color=discord.Color.green()
        )

    @discord.ui.button(label="💰 Nhập tiền", style=discord.ButtonStyle.success, row=2, custom_id="invest_money")
    async def invest(self, i, b):
        if not self.exchange or not self.symbol:
            await i.response.send_message(
                "❌ Hãy chọn **sàn** và **cổ phiếu** trước.",
                ephemeral=True
            )
            return
        await i.response.send_modal(InvestMoneyModal(self.exchange, self.symbol))

    @discord.ui.button(label="🔄 Đổi sàn", style=discord.ButtonStyle.secondary, row=2, custom_id="change_exchange")
    async def change_exchange(self, i, b):
        self.exchange = None
        self.symbol = None
        self.clear_items()
        self.add_item(ExchangeSelect())
        await i.response.edit_message(embed=self.make_embed(), view=self)


class PayModal(discord.ui.Modal, title='💸 PAY VND'):
    user_id = discord.ui.TextInput(label='ID Discord người nhận')
    amount = discord.ui.TextInput(label='Số tiền VND')
    async def on_submit(self, i):
        try: uid=int(self.user_id.value); amount=int(self.amount.value.replace(',','').replace('.','')); assert amount>0 and uid!=i.user.id
        except: return await i.response.send_message('❌ Thông tin không hợp lệ.', ephemeral=True)
        u=user(i.user.id)
        if u[1] < amount: return await i.response.send_message(f'❌ Không đủ tiền: {fmt(u[1])} VND.', ephemeral=True)
        user(uid); cur.execute('UPDATE users SET vnd=vnd-? WHERE user_id=?',(amount,i.user.id)); cur.execute('UPDATE users SET vnd=vnd+? WHERE user_id=?',(amount,uid)); db.commit()
        await i.response.send_message(f'✅ Đã chuyển **{fmt(amount)} VND** cho <@{uid}>.', ephemeral=True)

class MainView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='📊 Thị trường',style=discord.ButtonStyle.primary,custom_id='market')
    async def market(self,i,b):
        await i.response.send_message(
            embed=make_market_embed(),
            view=MarketBoardView(),
            ephemeral=True
        )
    @discord.ui.button(label='🛒 Mua',style=discord.ButtonStyle.success,custom_id='buy')
    async def buy(self,i,b): await i.response.send_modal(BuyModal())
    @discord.ui.button(label='💸 Bán',style=discord.ButtonStyle.danger,custom_id='sell')
    async def sell(self,i,b): await i.response.send_modal(SellModal())
    @discord.ui.button(label='💸 Pay',style=discord.ButtonStyle.secondary,custom_id='pay')
    async def pay(self,i,b): await i.response.send_modal(PayModal())
    @discord.ui.button(label='🏦 Ngân hàng',style=discord.ButtonStyle.secondary,custom_id='bank')
    async def bank(self,i,b):
        u=user(i.user.id); e=discord.Embed(title='🏦 NGÂN HÀNG',color=discord.Color.gold()); e.description=f'👤 {i.user.mention}\n\n🇻🇳 VND: **{fmt(u[1])} ₫**\n🇺🇸 USD: **${u[2]:,.2f}**\n₿ BTC: **{u[3]:.8f}**\n\n💱 Tỷ giá giả lập\n1 USD = 26,000 VND\n1 BTC = 2,800,000,000 VND'; await i.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label='🎁 Daily',style=discord.ButtonStyle.primary,custom_id='daily')
    async def daily(self,i,b):
        u=user(i.user.id); now=int(time.time()); cd=86400
        if now-u[4]<cd:
            rem=cd-(now-u[4]); await i.response.send_message(f'⏳ Còn **{rem//3600} giờ {(rem%3600)//60} phút**.',ephemeral=True); return
        reward=random.randint(10000,50000); cur.execute('UPDATE users SET vnd=vnd+?,last_daily=? WHERE user_id=?',(reward,now,i.user.id)); db.commit(); await i.response.send_message(f'🎁 Bạn nhận được **{fmt(reward)} VND**!',ephemeral=True)
    @discord.ui.button(label='📦 Tài sản',style=discord.ButtonStyle.secondary,custom_id='portfolio')
    async def portfolio(self,i,b):
        u=user(i.user.id); cur.execute('SELECT h.symbol,h.amount,s.price,s.name FROM holdings h JOIN stocks s ON s.symbol=h.symbol WHERE h.user_id=? AND h.amount>0 ORDER BY h.symbol',(i.user.id,)); rows=cur.fetchall(); lines=[]; total=0
        for s,a,p,n in rows: v=a*p; total+=v; lines.append(f'**{s}** {n}: `{a}` × {p:,.2f} = **{v:,.2f}**')
        e=discord.Embed(title='📦 DANH MỤC ĐẦU TƯ',description='\n'.join(lines) if lines else 'Chưa có cổ phiếu nào.',color=discord.Color.blurple()); e.add_field(name='💵 VND',value=fmt(u[1])+' ₫'); e.add_field(name='📊 Giá trị cổ phiếu',value=f'{total:,.2f}'); await i.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label='🏆 BXH',style=discord.ButtonStyle.secondary,custom_id='leaderboard')
    async def leaderboard(self,i,b):
        cur.execute('SELECT user_id,vnd FROM users ORDER BY vnd DESC LIMIT 10'); rows=cur.fetchall(); text=[]
        for n,(uid,v) in enumerate(rows,1):
            m=i.guild.get_member(uid) if i.guild else None; text.append(f'**#{n}** {m.display_name if m else uid} — {fmt(v)} VND')
        await i.response.send_message(embed=discord.Embed(title='🏆 BẢNG XẾP HẠNG',description='\n'.join(text) or 'Chưa có người chơi.',color=discord.Color.gold()),ephemeral=True)

class BuyModal(discord.ui.Modal,title='🛒 MUA CỔ PHIẾU'):
    symbol=discord.ui.TextInput(label='Mã cổ phiếu',placeholder='VD: AAPL')
    amount=discord.ui.TextInput(label='Số lượng',placeholder='VD: 5')
    async def on_submit(self,i):
        s=self.symbol.value.strip().upper()
        try: a=int(self.amount.value); assert a>0
        except: await i.response.send_message('❌ Số lượng không hợp lệ.',ephemeral=True); return
        st=stock(s)
        if not st: await i.response.send_message('❌ Không tìm thấy mã cổ phiếu.',ephemeral=True); return
        total=st[3]*a; u=user(i.user.id)
        if u[1]<total: await i.response.send_message(f'❌ Không đủ tiền. Cần **{fmt(total)} VND**, có **{fmt(u[1])} VND**.',ephemeral=True); return
        cur.execute('UPDATE users SET vnd=vnd-? WHERE user_id=?',(total,i.user.id)); cur.execute('INSERT INTO holdings VALUES(?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET amount=amount+excluded.amount',(i.user.id,s,a)); db.commit(); await i.response.send_message(f'✅ Mua **{a} {s}** với giá **{fmt(total)} VND**.',ephemeral=True)

class SellModal(discord.ui.Modal,title='💸 BÁN CỔ PHIẾU'):
    symbol=discord.ui.TextInput(label='Mã cổ phiếu',placeholder='VD: AAPL')
    amount=discord.ui.TextInput(label='Số lượng',placeholder='VD: 5')
    async def on_submit(self,i):
        s=self.symbol.value.strip().upper()
        try: a=int(self.amount.value); assert a>0
        except: await i.response.send_message('❌ Số lượng không hợp lệ.',ephemeral=True); return
        st=stock(s)
        if not st: await i.response.send_message('❌ Không tìm thấy mã cổ phiếu.',ephemeral=True); return
        cur.execute('SELECT amount FROM holdings WHERE user_id=? AND symbol=?',(i.user.id,s)); h=cur.fetchone()
        if not h or h[0]<a: await i.response.send_message(f'❌ Bạn không có đủ cổ phiếu. Đang có: **{h[0] if h else 0}**.',ephemeral=True); return
        total=st[3]*a; cur.execute('UPDATE holdings SET amount=amount-? WHERE user_id=? AND symbol=?',(a,i.user.id,s)); cur.execute('UPDATE users SET vnd=vnd+? WHERE user_id=?',(total,i.user.id)); db.commit(); await i.response.send_message(f'✅ Bán **{a} {s}**, nhận **{fmt(total)} VND**.',ephemeral=True)

def market_board_text():
    cur.execute('SELECT symbol,name,exchange,price FROM stocks ORDER BY exchange,symbol')
    rows = cur.fetchall()
    lines = []
    for s, n, e, p in rows:
        old = price_history.get(s, p)
        change = p - old
        pct = (change / old * 100) if old else 0
        arrow = "🟢 ▲" if change > 0 else ("🔴 ▼" if change < 0 else "⚪")
        sign = "+" if change > 0 else ""
        lines.append(
            f"{arrow} **{s}** — `{e}`\n"
            f"💰 {fmt(p)} VND  |  {sign}{fmt(change)} ({sign}{pct:.2f}%)"
        )
    return "\n".join(lines)


class MarketBoardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔄 Làm mới bảng", style=discord.ButtonStyle.primary)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=make_market_embed(), view=self)

    @discord.ui.button(label="🚨 Sập sàn", style=discord.ButtonStyle.danger)
    async def crash_info(self, i, b):
        await i.response.send_message(
            f"🚨 **Sập sàn ngẫu nhiên**\n{last_crash_info}",
            ephemeral=True
        )


def make_market_embed():
    e = discord.Embed(
        title="📊 BẢNG GIÁ CHỨNG KHOÁN",
        description=market_board_text()[:4000],
        color=discord.Color.green()
    )
    e.add_field(
        name="📈 Tăng / giảm",
        value="🟢 ▲ Tăng  •  🔴 ▼ Giảm  •  ⚪ Không đổi",
        inline=False
    )
    e.add_field(name="🚨 Sập sàn gần nhất", value=last_crash_info, inline=False)
    e.set_footer(text="Giá tự động thay đổi mỗi 30 giây.")
    return e


@tasks.loop(seconds=30)
async def market_update():
    cur.execute('SELECT symbol,price FROM stocks')
    rows = cur.fetchall()
    for s, p in rows:
        price_history[s] = p
        new_price = max(1, p * (1 + random.uniform(-.08, .08)))
        cur.execute('UPDATE stocks SET price=? WHERE symbol=?', (new_price, s))
    db.commit()


@tasks.loop(minutes=30)
async def random_crash():
    global last_crash_info

    # Mỗi 30 phút có 35% xác suất xảy ra sập sàn.
    if random.random() > 0.35:
        return

    cur.execute('SELECT symbol,price FROM stocks')
    rows = cur.fetchall()
    if not rows:
        return

    victims = random.sample(rows, min(3, len(rows)))
    crashed = []

    for s, p in victims:
        price_history[s] = p
        drop = random.uniform(.40, .80)
        new_price = max(1, p * (1 - drop))
        cur.execute('UPDATE stocks SET price=? WHERE symbol=?', (new_price, s))
        crashed.append(f"**{s}** -{drop*100:.0f}%")

    db.commit()

    last_crash_info = (
        f"🕒 {time.strftime('%H:%M:%S %d/%m/%Y')} — "
        + ", ".join(crashed)
    )
    print("🚨 SẬP SÀN:", last_crash_info)


@bot.command(name="stock")
async def stock_cmd(ctx):
    e = discord.Embed(
        title='📈 GLOBAL STOCK MARKET',
        description='Bấm **📊 Thị trường** để xem bảng tăng/giảm, sau đó chọn sàn → cổ phiếu → nhập tiền.',
        color=discord.Color.blurple()
    )
    e.add_field(
        name='🏦 Các sàn',
        value='NYSE • NASDAQ • HOSE • HNX • TSE • HKEX • LSE • SSE • KRX • SGX • UPCoM'
    )
    e.add_field(name='💰 Tiền', value='VND • USD • BTC')
    e.set_footer(text='⚠️ Tất cả đều là tiền và giá giả lập.')
    await ctx.send(embed=e, view=MainView())


@bot.command(name="balance")
async def balance(ctx):
    u=user(ctx.author.id); await ctx.send(f'🏦 **TÀI KHOẢN**\n\n🇻🇳 VND: **{fmt(u[1])} ₫**\n🇺🇸 USD: **${u[2]:,.2f}**\n₿ BTC: **{u[3]:.8f}**')

@bot.command(name="daily")
async def daily_cmd(ctx):
    u=user(ctx.author.id)
    now=int(time.time())
    cd=86400
    if now-u[4]<cd:
        rem=cd-(now-u[4])
        await ctx.send(f'⏳ Bạn đã nhận Daily rồi. Còn **{rem//3600} giờ {(rem%3600)//60} phút**.')
        return
    reward=random.randint(10000,50000)
    cur.execute('UPDATE users SET vnd=vnd+?,last_daily=? WHERE user_id=?',(reward,now,ctx.author.id))
    db.commit()
    await ctx.send(f'🎁 {ctx.author.mention} nhận được **{fmt(reward)} VND**!')

@bot.event
async def on_ready():
    await bot.tree.sync(); bot.add_view(MainView()); print(f'✅ Bot online: {bot.user}')
    if not market_update.is_running(): market_update.start()
    if not random_crash.is_running(): random_crash.start()

bot.run(TOKEN)
