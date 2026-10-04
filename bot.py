import discord
from discord.ext import commands, tasks
import sqlite3, random, time, os

TOKEN = os.getenv('TOKEN', 'DAN_TOKEN_BOT_VAO_DAY')
db = sqlite3.connect('stockbot.db')
cur = db.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, vnd REAL DEFAULT 10000000, usd REAL DEFAULT 1000, btc REAL DEFAULT 0, last_daily INTEGER DEFAULT 0)')
cur.execute('CREATE TABLE IF NOT EXISTS stocks (symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, price REAL)')
cur.execute('CREATE TABLE IF NOT EXISTS holdings (user_id INTEGER, symbol TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY(user_id,symbol))')
STOCKS=[('AAPL','Apple','NASDAQ',150),('MSFT','Microsoft','NASDAQ',420),('NVDA','NVIDIA','NASDAQ',180),('TSLA','Tesla','NASDAQ',350),('JPM','JPMorgan Chase','NYSE',220),('VIC','Vingroup','HOSE',45000),('VHM','Vinhomes','HOSE',52000),('FPT','FPT','HOSE',135000),('HPG','Hoa Phat','HOSE',28000),('VCB','Vietcombank','HOSE',95000),('7203','Toyota','TSE',2800),('9984','SoftBank','TSE',8500),('0700','Tencent','HKEX',520)]
for s in STOCKS: cur.execute('INSERT OR IGNORE INTO stocks VALUES (?,?,?,?)',s)
db.commit()
intents=discord.Intents.default(); bot=commands.Bot(command_prefix='!', intents=intents)

def user(uid):
    cur.execute('SELECT * FROM users WHERE user_id=?',(uid,)); r=cur.fetchone()
    if not r:
        cur.execute('INSERT INTO users(user_id) VALUES(?)',(uid,)); db.commit(); cur.execute('SELECT * FROM users WHERE user_id=?',(uid,)); r=cur.fetchone()
    return r

def stock(sym):
    cur.execute('SELECT symbol,name,exchange,price FROM stocks WHERE symbol=?',(sym.upper(),)); return cur.fetchone()

def fmt(x): return f'{x:,.0f}'

class MainView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='📊 Thị trường',style=discord.ButtonStyle.primary,custom_id='market')
    async def market(self,i,b):
        cur.execute('SELECT symbol,name,exchange,price FROM stocks ORDER BY exchange,symbol'); rows=cur.fetchall()
        text='\n\n'.join(f'**{s}** — {n}\n`{e}`  💰 {p:,.2f}' for s,n,e,p in rows)
        await i.response.send_message(embed=discord.Embed(title='📊 GLOBAL STOCK MARKET',description=text[:4000],color=discord.Color.green()),ephemeral=True)
    @discord.ui.button(label='🛒 Mua',style=discord.ButtonStyle.success,custom_id='buy')
    async def buy(self,i,b): await i.response.send_modal(BuyModal())
    @discord.ui.button(label='💸 Bán',style=discord.ButtonStyle.danger,custom_id='sell')
    async def sell(self,i,b): await i.response.send_modal(SellModal())
    @discord.ui.button(label='🏦 Ngân hàng',style=discord.ButtonStyle.secondary,custom_id='bank')
    async def bank(self,i,b):
        u=user(i.user.id); e=discord.Embed(title='🏦 NGÂN HÀNG',color=discord.Color.gold()); e.description=f'👤 {i.user.mention}\n\n🇻🇳 VND: **{fmt(u[1])} ₫**\n🇺🇸 USD: **${u[2]:,.2f}**\n₿ BTC: **{u[3]:.8f}**\n\n💱 Tỷ giá giả lập\n1 USD = 26,000 VND\n1 BTC = 2,800,000,000 VND'; await i.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label='🎁 Daily',style=discord.ButtonStyle.primary,custom_id='daily')
    async def daily(self,i,b):
        u=user(i.user.id); now=int(time.time()); cd=86400
        if now-u[4]<cd:
            rem=cd-(now-u[4]); await i.response.send_message(f'⏳ Còn **{rem//3600} giờ {(rem%3600)//60} phút**.',ephemeral=True); return
        reward=random.randint(50000,500000); cur.execute('UPDATE users SET vnd=vnd+?,last_daily=? WHERE user_id=?',(reward,now,i.user.id)); db.commit(); await i.response.send_message(f'🎁 Bạn nhận được **{fmt(reward)} VND**!',ephemeral=True)
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

@tasks.loop(seconds=30)
async def market_update():
    cur.execute('SELECT symbol,price FROM stocks')
    for s,p in cur.fetchall(): cur.execute('UPDATE stocks SET price=? WHERE symbol=?',(max(1,p*(1+random.uniform(-.08,.08))),s))
    db.commit()

@tasks.loop(hours=6)
async def random_crash():
    if random.random()>.35:return
    cur.execute('SELECT symbol,price FROM stocks'); rows=cur.fetchall(); victims=random.sample(rows,min(3,len(rows)))
    for s,p in victims: cur.execute('UPDATE stocks SET price=? WHERE symbol=?',(max(1,p*(1-random.uniform(.4,.8))),s))
    db.commit(); print('🚨 SẬP SÀN:',', '.join(x[0] for x in victims))

@bot.tree.command(name='stock',description='Mở bảng chứng khoán')
async def stock_cmd(i):
    e=discord.Embed(title='📈 GLOBAL STOCK MARKET',description='Chọn nút bên dưới để giao dịch.',color=discord.Color.blurple()); e.add_field(name='🏦 Các sàn',value='NYSE • NASDAQ • HOSE • HNX • TSE • HKEX'); e.add_field(name='💰 Tiền',value='VND • USD • BTC'); e.set_footer(text='⚠️ Tất cả đều là tiền và giá giả lập.'); await i.response.send_message(embed=e,view=MainView())

@bot.tree.command(name='balance',description='Xem số dư')
async def balance(i):
    u=user(i.user.id); await i.response.send_message(f'🏦 **TÀI KHOẢN**\n\n🇻🇳 VND: **{fmt(u[1])} ₫**\n🇺🇸 USD: **${u[2]:,.2f}**\n₿ BTC: **{u[3]:.8f}**',ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync(); bot.add_view(MainView()); print(f'✅ Bot online: {bot.user}')
    if not market_update.is_running(): market_update.start()
    if not random_crash.is_running(): random_crash.start()

bot.run(TOKEN)
