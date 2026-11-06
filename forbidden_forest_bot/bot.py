"""Forbidden Forest strategic event bot. discord.py >=2.4; one Railway replica + persistent volume."""
from __future__ import annotations
import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import random
import secrets
import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('forest')
TOKEN = os.getenv('DISCORD_TOKEN', '')
GUILD = int(os.getenv('GUILD_ID', '0'))
CHANNEL = int(os.getenv('EVENT_CHANNEL_ID', '1567980502965551144'))
ROLE = int(os.getenv('ROLE_ID', '1567982021106602065'))
FREE_PLAY = os.getenv('FREE_PLAY_MODE', 'true').lower() in ('1','true','yes','on')
HOSTS = {int(s.strip()) for s in os.getenv('HOST_IDS', '1501587787294703657').split(',') if s.strip()}
DB_FILE = os.getenv('DATABASE_PATH', '/data/forest.sqlite3')
START = dt.datetime(2026, 11, 8, 0, 0, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 11, 11, 0, 0, tzinfo=dt.timezone.utc)
BONUS_END = END + dt.timedelta(hours=24)
CATEGORIES = ['explore']*10 + ['relic']*10 + ['survival']*8 + ['camp']*6 + ['mystery']*6
SCENES = {
 'explore': ('🌲 The Forking Trail', 'A hidden path promises supplies and ancient secrets.', 'grove'),
 'relic': ('💎 The Forgotten Relic', 'A valuable artefact lies beyond an unstable passage.', 'chest'),
 'survival': ('🌉 The Broken Crossing', 'The forest tests your endurance and preparation.', 'ravine'),
 'camp': ('🔥 The Traveller’s Camp', 'A sheltered camp offers a chance to recover.', 'merchant'),
 'mystery': ('🔮 The Whispering Shrine', 'A forgotten puzzle guards an enchanted discovery.', 'shrine'),
}
TALENTS = {'scout':'🧭 Scout — see the next encounter type', 'guardian':'🛡️ Guardian — reduce health damage by 5', 'collector':'💎 Collector — +10 artefact points on relic successes'}
UTC = dt.timezone.utc
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)
forest = app_commands.Group(name='forest', description='Forbidden Forest adventure')
mutex = asyncio.Lock()
conn: sqlite3.Connection

def now(): return dt.datetime.now(UTC)
def phase():
    if now() < START: return 'upcoming'
    if now() < END: return 'open'
    if now() < BONUS_END: return 'bonus'
    return 'ended'

def db_init():
    global conn
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (
      uid INTEGER NOT NULL, mode TEXT NOT NULL, data TEXT NOT NULL,
      PRIMARY KEY(uid, mode));
    CREATE TABLE IF NOT EXISTS actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, uid INTEGER NOT NULL,
      mode TEXT NOT NULL, step INTEGER NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL,
      UNIQUE(uid,mode,step));
    ''')

def meta(k):
    r=conn.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone()
    return r['value'] if r else None

def set_meta(k,v): conn.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))

def get_run(uid,mode):
    r=conn.execute('SELECT data FROM runs WHERE uid=? AND mode=?',(uid,mode)).fetchone()
    return json.loads(r['data']) if r else None

def save(uid,mode,s):
    conn.execute('INSERT INTO runs VALUES(?,?,?) ON CONFLICT(uid,mode) DO UPDATE SET data=excluded.data',(uid,mode,json.dumps(s,sort_keys=True)))

def deck(seed):
    # Six evenly spaced camps, same category quotas for everyone.
    # Every segment of the adventure contains at most seven non-camp encounters.
    r=random.Random(int(hashlib.sha256((seed+'deck').encode()).hexdigest(),16))
    others=[x for x in CATEGORIES if x!='camp']
    r.shuffle(others)
    camp_positions={5,12,19,26,33,38}  # zero-indexed: encounters 6,13,20,27,34,39
    it=iter(others)
    return ['camp' if i in camp_positions else next(it) for i in range(40)]


def new_run(uid,mode):
    seed=secrets.token_hex(16)
    return dict(seed=seed,deck=deck(seed),step=0,hp=100,en=100,sup=5,potions=1,
                talent=None,art=0,challenge=0,objective=0,artifacts={},
                risky=0,explored=0,rested=0,recover_used=0,emergency_used=0,spent=0,finished=False,escaped=False,
                score=None,started=now().isoformat(),ended=None)

def current_kind(s): return s['deck'][s['step']]

def objectives(s):
    return [s['explored']>=4, s['risky']>=4, len(s['artifacts'])>=3]

def scoring(s):
    if s['score'] is not None: return s['score']
    # Capped categories prevent score inflation and reward the full adventure.
    obj=100*sum(objectives(s))
    survival=(150 if s['escaped'] else 0)
    resource=(min(100,(s['hp']+s['en'])//2) if s['escaped'] else 0)
    return min(1000,s['art'])+obj+min(200,s['challenge'])+survival+resource

def finish(s,escaped):
    s['finished']=True; s['escaped']=bool(escaped and s['hp']>0)
    s['ended']=now().isoformat()
    # A defeated/uncompleted run loses 25% of unbanked artefact points.
    if not s['escaped']: s['art']=s['art']*3//4
    s['objective']=100*sum(objectives(s))
    s['score']=scoring(s)

def options(s):
    kind=current_kind(s)
    # No hidden success rolls: all costs and outcomes are deterministic and disclosed.
    return {
      'explore': [('Search carefully','−8 energy, +1 supply, +25 challenge pts',8,0,0,1,0,25,0),
                  ('Explore the depths','−16 energy, −8 health, +2 supplies, +50 challenge pts',16,8,0,2,0,50,0),
                  ('Take the shortcut','−4 energy, no rewards',4,0,0,0,0,0,0)],
      'relic': [('Secure the relic','−10 energy, −1 supply, +65 artefact pts',10,0,1,0,65,0,0),
                ('Force the vault','−22 energy, −18 health, +110 artefact pts',22,18,0,0,110,0,0),
                ('Leave it','−3 energy, no reward',3,0,0,0,0,0,0)],
      'survival': [('Build a safe crossing','−8 energy, −1 supply, +15 challenge pts',8,0,1,0,0,15,0),
                   ('Brave the crossing','−14 energy, −18 health, +35 challenge pts',14,18,0,0,0,35,0),
                   ('Take a detour','−5 energy, no reward',5,0,0,0,0,0,0)],
      'camp': [('Rest by the fire','−1 supply, +55 energy',0,0,1,0,0,0,55),
               ('Forage for berries','−5 energy, +20 energy, +1 supply (net +15 energy)',5,0,0,1,0,0,20),
               ('Drink a potion','Consume 1 potion, +25 energy',0,0,0,0,0,0,25)],
      'mystery': [('Study the runes','−12 energy, +35 challenge pts',12,0,0,0,0,35,0),
                  ('Claim the enchanted prize','−18 energy, −12 health, +75 artefact pts',18,12,0,0,75,0,0),
                  ('Make a healing offering','−1 supply, +15 health',0,-15,1,0,0,0,0)],
    }[kind]

def action_allowed(s,choice):
    opts=options(s)
    if not 0<=choice<len(opts): return False,'Invalid choice.'
    o=opts[choice]
    if s['en']<o[2]: return False,'Not enough energy. Use `/forest recover` to trade a supply for energy.'
    if s['sup']<o[4]: return False,'Not enough supplies. Choose another option.'
    if current_kind(s)=='camp' and choice==2 and s['potions']<1: return False,'You have no potions.'
    return True,''

def apply(s,choice):
    kind=current_kind(s); o=options(s)[choice]
    s['en']=max(0,min(100,s['en']-o[2]+o[8]))
    damage=o[3]
    if damage>0 and s['talent']=='guardian': damage=max(0,damage-5)
    s['hp']=max(0,min(100,s['hp']-damage))
    s['sup']=min(12,s['sup']-o[4]+o[5])
    art=o[6]
    if art and s['talent']=='collector' and kind=='relic': art+=10
    s['art']=min(1000,s['art']+art)
    s['challenge']=min(200,s['challenge']+o[7])
    s['spent']+=o[2]
    if kind=='explore' and choice in (0,1): s['explored']+=1
    if (kind in ('relic','survival','mystery') and choice==1) or (kind=='explore' and choice==1): s['risky']+=1
    if art:
        label={'relic':'Forest Relic','mystery':'Enchanted Rune'}[kind]
        s['artifacts'][label]=s['artifacts'].get(label,0)+1
        # Distinct relic types are deterministically assigned by stage.
        if kind=='relic':
            label=['Bronze Acorn','Silver Maple Leaf','Golden Compass','Crown of the Forest'][min(3,s['step']//10)]
            s['artifacts'][label]=s['artifacts'].get(label,0)+1
    if kind=='camp':
        s['rested']+=1
        if choice==2: s['potions']-=1
    s['step']+=1
    if s['hp']<=0: finish(s,False)
    elif s['step']>=40:
        # The final gate requires sufficient strength to get out alive.
        # A player who reaches encounter 40 exhausted is defeated.
        finish(s, s['hp']>=25 and s['en']>=15)
    return o[0]

def scene(s,mode):
    if s['finished']:
        e=discord.Embed(title='🏁 Adventure completed',description=f"**Final score:** {s['score']:,}/1,750\n**Result:** {'Escaped' if s['escaped'] else 'Defeated / unfinished'}\n**Encounters:** {s['step']}/40\nFree-play scores do not count towards official prizes.",color=0xC39248)
        return e,None
    kind=current_kind(s); title,description,filename=SCENES[kind]
    e=discord.Embed(title=f'{title} • {s["step"]+1}/40',description=description,color=0xAD743C)
    e.add_field(name='Resources',value=f'❤️ {s["hp"]}/100  ⚡ {s["en"]}/100  🎒 {s["sup"]}  🧪 {s["potions"]}',inline=False)
    e.add_field(name='Progress',value=f'💎 Artefacts: {s["art"]}/1,000  ⚔️ Challenges: {s["challenge"]}/200\n🎯 Objectives: {sum(objectives(s))}/3  🌿 Talent: {s["talent"] or "Not chosen"}',inline=False)
    e.add_field(name='Your choices',value='\n'.join(f'**{i+1}. {o[0]}** — {o[1]}' for i,o in enumerate(options(s))),inline=False)
    if s['step'] in (5,10,15,20,25,30,35) and s['step']<39:
        e.add_field(name='🌫️ Trail ahead',value='Upcoming: **'+', '.join(x.title() for x in s['deck'][s['step']+1:min(40,s['step']+3)])+'**',inline=False)
    if s['step'] in (10,20,30):
        e.add_field(name='📜 Expedition report',value=f'Risky choices: **{s["risky"]}** · Searches: **{s["explored"]}** · Camps visited: **{s["rested"]}** · Standard recoveries: **{s["recover_used"]}/2** · Emergency used: **{s.get("emergency_used",0)}/1**',inline=False)
    if s['talent']=='scout' and s['step']<39:
        e.add_field(name='Scout insight',value=f'Next encounter: **{s["deck"][s["step"]+1].title()}**',inline=False)
    e.set_footer(text='Costs and rewards are disclosed. Use /forest recover or /forest emergency if stuck; /forest resume refreshes buttons.')
    path=Path(__file__).parent/'encounter_art'/f'{filename}.jpg'
    f=discord.File(path,filename='scene.jpg') if path.exists() else None
    if f: e.set_image(url='attachment://scene.jpg')
    return e,f

async def send_scene(interaction,s,mode,notice=''):
    e,f=scene(s,mode)
    kwargs={'embed':e,'ephemeral':True}
    if f: kwargs['file']=f
    if not s['finished']:
        kwargs['view']=AdventureView(interaction.user.id,mode,s['step'])
    if notice: kwargs['content']=notice
    if interaction.response.is_done(): await interaction.followup.send(**kwargs)
    else: await interaction.response.send_message(**kwargs)

class AdventureView(discord.ui.View):
    def __init__(self,uid,mode,step):
        super().__init__(timeout=600)
        self.uid,self.mode,self.step=uid,mode,step
        s=get_run(uid,mode)
        for i,o in enumerate(options(s)):
            b=discord.ui.Button(label=o[0][:80],style=[discord.ButtonStyle.primary,discord.ButtonStyle.success,discord.ButtonStyle.secondary][i],custom_id=f'forest:{mode}:{uid}:{step}:{i}')
            b.callback=self.choice_callback(i)
            self.add_item(b)
        if mode in ('main','free') and step in (20,30,35):
            b=discord.ui.Button(label='🚪 Escape & bank score',style=discord.ButtonStyle.danger)
            b.callback=self.escape_callback
            self.add_item(b)
        # Allow a stranded player to end their run; never strand them permanently.
        if not any(action_allowed(s,i)[0] for i in range(len(options(s)))):
            b=discord.ui.Button(label='🏳️ Admit defeat',style=discord.ButtonStyle.danger,row=1)
            b.callback=self.defeat_callback
            self.add_item(b)
        if step==10 and s['talent'] is None:
            for i,t in enumerate(TALENTS):
                b=discord.ui.Button(label=f'Choose {t.title()}',style=discord.ButtonStyle.secondary,row=1)
                b.callback=self.talent_callback(t)
                self.add_item(b)

    async def check(self,interaction):
        if interaction.user.id!=self.uid:
            await interaction.response.send_message('This is not your adventure.',ephemeral=True); return False
        if self.mode=='main' and not START<=now()<END:
            await interaction.response.send_message('The main event is not open.',ephemeral=True); return False
        if self.mode=='test' and self.uid not in HOSTS:
            await interaction.response.send_message('Host testing only.',ephemeral=True); return False
        return True

    def choice_callback(self,i):
        async def callback(interaction):
            if not await self.check(interaction): return
            await interaction.response.defer(ephemeral=True,thinking=True)
            async with mutex:
                conn.execute('BEGIN IMMEDIATE')
                try:
                    s=get_run(self.uid,self.mode)
                    if not s or s['finished'] or s['step']!=self.step:
                        conn.execute('ROLLBACK'); return await interaction.followup.send('This encounter is outdated. Use `/forest resume`.',ephemeral=True)
                    if s['step']==10 and s['talent'] is None:
                        conn.execute('ROLLBACK'); return await interaction.followup.send('Choose a forest talent first, using the buttons below.',ephemeral=True)
                    ok,why=action_allowed(s,i)
                    if not ok:
                        conn.execute('ROLLBACK'); return await interaction.followup.send(why,ephemeral=True)
                    outcome=apply(s,i)
                    save(self.uid,self.mode,s)
                    conn.execute('INSERT INTO actions(at,uid,mode,step,action,result) VALUES(?,?,?,?,?,?)',(now().isoformat(),self.uid,self.mode,self.step,str(i),outcome))
                    conn.execute('COMMIT')
                except Exception:
                    conn.execute('ROLLBACK'); log.exception('Action failed'); raise
            await send_scene(interaction,s,self.mode,f'🍁 **{outcome}** — Encounter {self.step+1} resolved.')
        return callback

    def talent_callback(self,t):
        async def callback(interaction):
            if not await self.check(interaction): return
            async with mutex:
                s=get_run(self.uid,self.mode)
                if not s or s['finished'] or s['step']!=self.step or s['step']!=10 or s['talent'] is not None:
                    return await interaction.response.send_message('Talent selection is no longer available.',ephemeral=True)
                s['talent']=t; save(self.uid,self.mode,s)
            await send_scene(interaction,s,self.mode,f'🌿 Talent selected: **{TALENTS[t]}**')
        return callback

    async def defeat_callback(self,interaction):
        if not await self.check(interaction): return
        async with mutex:
            s=get_run(self.uid,self.mode)
            if not s or s['finished'] or s['step']!=self.step:
                return await interaction.response.send_message('This encounter is outdated.',ephemeral=True)
            if any(action_allowed(s,i)[0] for i in range(len(options(s)))):
                return await interaction.response.send_message('An encounter choice is available; use it to continue.',ephemeral=True)
            finish(s,False); save(self.uid,self.mode,s)
        await send_scene(interaction,s,self.mode,'🏳️ Your adventure ended in the forest. Your final score is recorded.')

    async def escape_callback(self,interaction):
        if not await self.check(interaction): return
        async with mutex:
            s=get_run(self.uid,self.mode)
            if not s or s['finished'] or s['step']!=self.step or self.step not in (20,30,35):
                return await interaction.response.send_message('This escape option is outdated.',ephemeral=True)
            finish(s,True); save(self.uid,self.mode,s)
        await send_scene(interaction,s,self.mode,'🚪 You escaped and banked your score.')

class EntryView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label='Begin / Resume Adventure',emoji='🌲',style=discord.ButtonStyle.success,custom_id='forest:entry:v3')
    async def enter(self,interaction,button): await open_run(interaction,'free' if FREE_PLAY else 'main')

async def open_run(interaction,mode):
    if not interaction.guild or interaction.guild.id!=GUILD:
        return await interaction.response.send_message('Use this in the event server.',ephemeral=True)
    if mode=='free' and not FREE_PLAY:
        return await interaction.response.send_message('Free play is disabled.',ephemeral=True)
    if mode=='main':
        if phase()!='open': return await interaction.response.send_message('The event is not accepting new adventures right now.',ephemeral=True)
        if not isinstance(interaction.user,discord.Member) or ROLE not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message('Click 🍁 Join Adventure on the signup panel to receive the event role first.',ephemeral=True)
    if mode=='test' and interaction.user.id not in HOSTS:
        return await interaction.response.send_message('Host-only testing.',ephemeral=True)
    async with mutex:
        s=get_run(interaction.user.id,mode)
        if s is None:
            s=new_run(interaction.user.id,mode); save(interaction.user.id,mode,s)
    await send_scene(interaction,s,mode)

@forest.command(name='help',description='Detailed guide to the forest, scoring, survival, commands and prizes')
@app_commands.describe(topic='Which part of the guide would you like to read?')
@app_commands.choices(topic=[
    app_commands.Choice(name='Overview & schedule',value='overview'),
    app_commands.Choice(name='How to play & survival',value='survival'),
    app_commands.Choice(name='Scoring, objectives & prizes',value='scoring'),
    app_commands.Choice(name='Commands & host testing',value='commands'),
    app_commands.Choice(name='Fairness & tiebreakers',value='fairness'),
])
async def help_cmd(interaction:discord.Interaction, topic:str='overview'):
    pages={
      'overview': (
        '📅 **Open:** 8 Nov 2026, 00:00 GMT\n'
        '🏁 **Close:** 11 Nov 2026, 00:00 GMT (72 hours)\n\n'
        '**Join:** Click 🍁 Join Adventure on the registration panel to receive the event role. '
        'Use `/forest play` anytime in free-play mode, and `/forest replay` after finishing to try again.\n\n'
        '**Free play:** Unlimited completed adventures, with separate scores that do not count for prizes. The official event allows one attempt. Your journey has up to **40 encounters**. '
        'You may pause and use `/forest resume`, but cannot restart an official adventure. '
        'Each route is individually shuffled using balanced encounter-type quotas.\n\n'
        '**The objective:** Collect artefacts, complete objectives, manage resources, '
        'survive the forest and earn the highest final score.\n\n'
        'Use `/forest help topic:How to play & survival` for the survival rules.'
      ),
      'survival': (
        '**❤️ Health:** Starts at 100. Reaching 0 means defeat immediately.\n'
        '**⚡ Energy:** Starts at 100. Actions require energy; if you cannot afford a choice, '
        'select a cheaper option or recover.\n'
        '**🎒 Supplies:** Starts at 5. Used for safer choices and recovery.\n'
        '**🧪 Potion:** Starts at 1; can restore energy at campsites.\n\n'
        '**Recovery:** `/forest recover` spends 1 supply to restore 30 energy, '
        'up to **2 uses per adventure**. Campsites also offer recovery choices. '
        'Energy does not regenerate just by waiting. Six camps are spaced across the adventure.\n'
        '**Emergency:** `/forest emergency` trades 15 health for 30 energy, once per adventure (requires more than 15 health).\n\n'
        '**🌿 Talent:** At encounter 11 choose Scout, Guardian or Collector. '
        'Guardian reduces damage; Collector improves certain relic rewards; '
        'Scout is an information-focused choice.\n\n'
        '**🚪 Early escape:** After encounters 20, 30 or 35, you can leave and bank your score. '
        'Escaping ends your run permanently.\n'
        '**Trail reports:** At encounters 11, 21 and 31 you receive a summary of your choices. Checkpoint hints reveal upcoming encounter types.\n\n'
        '**☠️ Final Gate:** To escape at encounter 40 you must finish with '
        '**at least 25 health AND 15 energy**. Reaching 40 without both means defeat, '
        'even if you still have some health.\n\n'
        '**Defeat:** Lose 25% of artefact points and receive no escape or remaining-resource bonus. '
        'An unfinished adventure at the deadline is also treated as defeated.\n\n'
        '**Strategy tip:** Taking every risky route can leave you too weak to escape; '
        'taking only easy routes can limit your score.'
      ),
      'scoring': (
        '**🏆 Highest final score wins (maximum 1,750):**\n'
        '💎 Artefacts: **up to 1,000**\n'
        '🎯 Objectives: **up to 300**\n'
        '🧩 Strategic challenges: **up to 200**\n'
        '🚪 Successful escape: **150**\n'
        '❤️⚡ Remaining health and energy: **up to 100** (only if escaped)\n\n'
        '**Three objectives:** Explore at least 4 times; take at least 4 demanding routes; '
        'collect at least 3 distinct artefact types. Each completed objective awards 100 points.\n\n'
        '**Prizes:**\n'
        '🥇 **1st:** 125c + HC Box\n'
        '🥈 **2nd:** 75c + HC Box\n'
        '🥉 **3rd:** 50c + HC Box\n\n'
        '**Important:** The highest artefact total alone does not guarantee first place. '
        'Survival, challenges and objectives all count.'
      ),
      'commands': (
        '**Player commands**\n'
        '`/forest help` — Open this guide; select a topic for more details.\n'
        '`/forest play` — Start or resume an unlimited free-play adventure.\n'
        '`/forest replay` — Start a new free-play adventure after finishing.\n'
        '`/forest official` — Your single official adventure during the event dates.\n'
        '`/forest resume` — Refresh the buttons for your current encounter.\n'
        '`/forest status` — See progress and current resources.\n'
        '`/forest inventory` — Check artefacts, potions, objectives and talent.\n'
        '`/forest recover` — Spend 1 supply for +30 energy (maximum twice).\n'
        '`/forest emergency` — Once per run, trade 15 health for +30 energy.\n'
        '`/forest leaderboard` — See results after finalisation.\n'
        '`/forest tiebreaker` — Play an assigned prize-position tiebreaker.\n\n'
        '**Host-only commands**\n'
        '`/forest panel` — Publish the 🍁 registration panel.\n'
        '`/forest dashboard` — Check participation and event status.\n'
        '`/forest logs` — Inspect activity logs.\n'
        '`/forest audit` — Check integrity conditions.\n'
        '`/forest test` — Play a separate test adventure any time.\n'
        '`/forest testreset` — Restart your test adventure.\n'
        '`/forest testjump encounter:30` — Jump to any encounter from 1 to 40.\n'
        '`/forest recover testing:True` — Recover in test mode.\n'
        '`/forest emergency testing:True` — Emergency recovery in test mode.'
      ),
      'fairness': (
        '**Fairness rules**\n'
        '• Unlimited free-play adventures are separate from the one official competition adventure.\n'
        '• Players receive the same encounter-type quotas, with evenly spaced camps and shuffled other encounters.\n'
        '• Resource costs and rewards are shown before choosing.\n'
        '• No speed-based scoring; think before you click.\n'
        '• Buttons are checked against your saved state to reject stale or duplicate actions.\n'
        '• Test adventures never contribute to official rankings.\n'
        '• Using alternate accounts or colluding is against the event rules; '
        'the bot cannot automatically detect every case.\n\n'
        '**Ties:** Compare final score, artefact points, completed objectives, '
        'then remaining health + energy. If a prize-position tie remains, '
        'eligible players receive a fixed five-question tiebreaker with a 24-hour window.\n\n'
        '**Deadline:** All official play ends 11 Nov 2026, 00:00 GMT. '
        'An unfinished run is defeated and scored accordingly.'
      )
    }
    if topic not in pages: topic='overview'
    labels={'overview':'Start Here','survival':'Survival & Escape','scoring':'Scoring & Prizes','commands':'All Commands','fairness':'Fairness & Ties'}
    e=discord.Embed(title=f'🌲 The Forbidden Forest — {labels[topic]}',description=pages[topic],color=0xA46A36)
    e.set_footer(text='Choose another /forest help topic to view the rest of the guide.')
    await interaction.response.send_message(embed=e,ephemeral=True)

@forest.command(name='play',description='Play anytime with unlimited replays while free-play mode is enabled')
async def play_cmd(interaction:discord.Interaction): await open_run(interaction,'free' if FREE_PLAY else 'main')
@forest.command(name='resume',description='Resume your current forest adventure')
async def resume_cmd(interaction:discord.Interaction): await open_run(interaction,'free' if FREE_PLAY else 'main')
@forest.command(name='replay',description='Start a fresh forest adventure (free-play mode only)')
async def replay_cmd(interaction:discord.Interaction):
    if not FREE_PLAY:
        return await interaction.response.send_message('Replays are disabled during the official competition.',ephemeral=True)
    if not interaction.guild or interaction.guild.id!=GUILD:
        return await interaction.response.send_message('Use this in the event server.',ephemeral=True)
    async with mutex:
        s=get_run(interaction.user.id,'free')
        if s and not s['finished']:
            return await interaction.response.send_message('Finish your current adventure before starting another. Use `/forest resume`.',ephemeral=True)
        conn.execute('DELETE FROM actions WHERE uid=? AND mode=?',(interaction.user.id,'free'))
        s=new_run(interaction.user.id,'free');save(interaction.user.id,'free',s)
    await send_scene(interaction,s,'free','🍁 A fresh adventure begins! Free-play scores do not count towards official prizes.')
@forest.command(name='official',description='Start or resume your one official competition adventure during the event')
async def official_cmd(interaction:discord.Interaction): await open_run(interaction,'main')
@forest.command(name='test',description='Host: play a separate test adventure before launch')
async def test_cmd(interaction:discord.Interaction): await open_run(interaction,'test')
@forest.command(name='testreset',description='Host: reset ONLY your separate test adventure')
async def testreset_cmd(interaction:discord.Interaction):
    if interaction.user.id not in HOSTS: return await interaction.response.send_message('Host-only.',ephemeral=True)
    async with mutex:
        conn.execute("DELETE FROM runs WHERE uid=? AND mode='test'",(interaction.user.id,))
        conn.execute("DELETE FROM actions WHERE uid=? AND mode='test'",(interaction.user.id,))
    await interaction.response.send_message('Test adventure reset. Use `/forest test` to begin again. Official data was not changed.',ephemeral=True)

@forest.command(name='testjump',description='Host: jump to any encounter (1–40) in your test adventure')
@app_commands.describe(encounter='Encounter to preview, from 1 to 40')
async def testjump_cmd(interaction:discord.Interaction, encounter:app_commands.Range[int,1,40]):
    if interaction.user.id not in HOSTS:
        return await interaction.response.send_message('Host-only testing.',ephemeral=True)
    if not interaction.guild or interaction.guild.id!=GUILD:
        return await interaction.response.send_message('Use this in the event server.',ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    async with mutex:
        conn.execute('BEGIN IMMEDIATE')
        try:
            s=get_run(interaction.user.id,'test')
            if s is None:
                s=new_run(interaction.user.id,'test')
            # Debug-only checkpoint: restore resources to make isolated encounters playable.
            # Reset accumulated scores so jumps cannot masquerade as a normal completed run.
            s['step']=encounter-1
            s['hp']=100
            s['en']=100
            s['sup']=5
            s['potions']=1
            s['art']=0
            s['challenge']=0
            s['objective']=0
            s['artifacts']={}
            s['risky']=0
            s['explored']=0
            s['rested']=0
            s['recover_used']=0
            s['emergency_used']=0
            s['spent']=0
            s['finished']=False
            s['escaped']=False
            s['score']=None
            s['ended']=None
            s['talent']='scout' if encounter>11 else None
            conn.execute("DELETE FROM actions WHERE uid=? AND mode='test'",(interaction.user.id,))
            save(interaction.user.id,'test',s)
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            log.exception('Test jump failed')
            await interaction.followup.send('Could not jump to that encounter. Check Railway logs.',ephemeral=True)
            return
    await send_scene(interaction,s,'test',f'🧪 Test checkpoint: encounter **{encounter}/40**. Test resources and score have been reset. Official progress is untouched.')

@forest.command(name='recover',description='Spend one supply to restore 30 energy (twice per run)')
@app_commands.describe(testing='Host only: recover energy in your separate test adventure')
async def recover_cmd(interaction:discord.Interaction, testing:bool=False):
    mode='test' if testing else ('free' if FREE_PLAY else 'main')
    if testing and interaction.user.id not in HOSTS: return await interaction.response.send_message('Host-only testing.',ephemeral=True)
    if not testing and not FREE_PLAY and phase()!='open': return await interaction.response.send_message('Recovery is only available during the official event.',ephemeral=True)
    async with mutex:
        s=get_run(interaction.user.id,mode)
        if not s or s['finished']: return await interaction.response.send_message('No active adventure.',ephemeral=True)
        if s['recover_used']>=2 or s['sup']<1 or s['en']>=100:
            return await interaction.response.send_message('Recovery unavailable: maximum two uses, at least one supply and energy below 100 required.',ephemeral=True)
        s['sup']-=1; s['en']=min(100,s['en']+30); s['recover_used']+=1; save(interaction.user.id,mode,s)
    await interaction.response.send_message(f'⚡ Recovered energy: **{s["en"]}/100**. Supplies: **{s["sup"]}**. Recovery uses: **{s["recover_used"]}/2**.',ephemeral=True)

@forest.command(name='emergency',description='Once per adventure: trade 15 health for 30 energy')
@app_commands.describe(testing='Host only: use in the separate test adventure')
async def emergency_cmd(interaction:discord.Interaction, testing:bool=False):
    mode='test' if testing else ('free' if FREE_PLAY else 'main')
    if testing and interaction.user.id not in HOSTS:
        return await interaction.response.send_message('Host-only testing.',ephemeral=True)
    if not testing and not FREE_PLAY and phase()!='open':
        return await interaction.response.send_message('Emergency recovery is only available during the official event.',ephemeral=True)
    async with mutex:
        s=get_run(interaction.user.id,mode)
        if not s or s['finished']:
            return await interaction.response.send_message('No active adventure.',ephemeral=True)
        if s.get('emergency_used',0)>=1:
            return await interaction.response.send_message('You have already used your one emergency recovery.',ephemeral=True)
        if s['hp']<=15 or s['en']>=100:
            return await interaction.response.send_message('You need more than 15 health and less than 100 energy to use emergency recovery.',ephemeral=True)
        s['hp']-=15; s['en']=min(100,s['en']+30); s['emergency_used']=1
        save(interaction.user.id,mode,s)
    await interaction.response.send_message(f'🆘 Emergency recovery used! ❤️ {s["hp"]}/100 · ⚡ {s["en"]}/100. This cannot be used again.',ephemeral=True)

@forest.command(name='status',description='View your adventure progress')
async def status_cmd(interaction:discord.Interaction):
    s=get_run(interaction.user.id,'free' if FREE_PLAY else 'main')
    if not s: return await interaction.response.send_message('No adventure yet.',ephemeral=True)
    await interaction.response.send_message(f'🌲 {s["step"]}/40 encounters | ❤️ {s["hp"]} | ⚡ {s["en"]} | 🎒 {s["sup"]} | 💎 {s["art"]} | 🎯 {sum(objectives(s))}/3 | {"Finished" if s["finished"] else "Active"}',ephemeral=True)

@forest.command(name='inventory',description='See your artefacts, potions and objectives')
async def inventory_cmd(interaction:discord.Interaction):
    s=get_run(interaction.user.id,'free' if FREE_PLAY else 'main')
    if not s: return await interaction.response.send_message('No adventure yet.',ephemeral=True)
    bag='\n'.join(f'• {k}: {v}' for k,v in s['artifacts'].items()) or 'No artefacts yet.'
    await interaction.response.send_message(embed=discord.Embed(title='🎒 Your Forest Inventory',description=f'{bag}\n\n🧪 Potions: {s["potions"]}\n🎯 Objectives: {sum(objectives(s))}/3\n🌿 Talent: {s["talent"] or "Not chosen"}',color=0x9D6B3D),ephemeral=True)

async def host_only(interaction):
    if interaction.user.id in HOSTS: return True
    await interaction.response.send_message('Host-only command.',ephemeral=True); return False

class SignupView(discord.ui.View):
    """Persistent alternative to reactions: survives restarts."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Join Adventure',emoji='🍁',style=discord.ButtonStyle.success,custom_id='forest:signup:join')
    async def join(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self._toggle(interaction,True)

    @discord.ui.button(label='Leave Signup',emoji='🚪',style=discord.ButtonStyle.secondary,custom_id='forest:signup:leave')
    async def leave(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self._toggle(interaction,False)

    async def _toggle(self,interaction:discord.Interaction,join:bool):
        if not interaction.guild or interaction.guild.id!=GUILD:
            return await interaction.response.send_message('Use this in the event server.',ephemeral=True)
        if str(interaction.message.id)!=meta('panel_message'):
            return await interaction.response.send_message('This panel is outdated. Please use the newest signup panel.',ephemeral=True)
        role=interaction.guild.get_role(ROLE)
        if role is None:
            return await interaction.response.send_message('The event role was not found. Please contact the host.',ephemeral=True)
        try:
            member=interaction.user
            if not isinstance(member,discord.Member):
                member=await interaction.guild.fetch_member(interaction.user.id)
            if join:
                await member.add_roles(role,reason='Forbidden Forest signup button')
            else:
                await member.remove_roles(role,reason='Forbidden Forest leave signup button')
        except discord.Forbidden:
            log.exception('Missing permission to assign Forest role')
            return await interaction.response.send_message('I cannot manage that role. Please ask the host to grant Manage Roles and move my role above the event role.',ephemeral=True)
        except discord.HTTPException:
            log.exception('Discord role change failed')
            return await interaction.response.send_message('Discord could not update your role. Please try again.',ephemeral=True)
        await interaction.response.send_message('🍁 You have joined The Forbidden Forest!' if join else 'You have left the signup list.',ephemeral=True)

@forest.command(name='panel',description='Host: post the 🍁 signup panel and graphic')
async def panel_cmd(interaction:discord.Interaction):
    if not await host_only(interaction): return
    if not interaction.channel: return await interaction.response.send_message('Use this in a server channel.',ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    e=discord.Embed(title='🍁 THE FORBIDDEN FOREST — JOIN THE ADVENTURE',description=(
        '🌲 **40 encounters. One adventure. Every choice matters.**\n\n'
        '**Click 🍁 Join Adventure below** (or react 🍁) to receive the event role for the official competition. You can use `/forest play` anytime for unlimited practice. '
        'Each adventurer gets a unique shuffled journey, with equal encounter opportunities.\n\n'
        '⚡ Manage health, energy, supplies and potions. Find artefacts, complete secret objectives, '
        'choose a forest talent and decide when to escape. Careful decisions protect you; challenging routes offer greater rewards.\n\n'
        '**🏆 WIN:** Highest final score (artefacts + objectives + strategic challenges + survival + resources), up to **1,750 points**.\n'
        '🥇 **125c + HC Box**\n🥈 **75c + HC Box**\n🥉 **50c + HC Box**\n\n'
        '🗓️ **Opens:** 8 Nov 2026, 12:00 AM GMT\n'
        '🗓️ **Closes:** 11 Nov 2026, 12:00 AM GMT\n'
        '📖 `/forest help` for complete rules and commands. Free-play scores are not eligible for prizes.\n\n'
        '**🍁 Join Adventure** assigns the role. **Leave Signup** removes it. Reactions also work if enabled.\n'
        '**Survival:** Six spaced camps and limited recovery help you prepare. The final gate requires 25 health and 15 energy.'),color=0xB67835)
    path=Path(__file__).parent/'panel.png'
    file=discord.File(path,filename='panel.png') if path.exists() else None
    if file: e.set_image(url='attachment://panel.png')
    try:
        msg=await interaction.channel.send(content='@everyone 🌲 **THE FORBIDDEN FOREST IS COMING!**',embed=e,file=file,view=SignupView(),allowed_mentions=discord.AllowedMentions(everyone=True))
    except discord.Forbidden:
        return await interaction.followup.send('I cannot post the signup panel here. Check Send Messages, Embed Links and Attach Files permissions.',ephemeral=True)
    set_meta('panel_message',msg.id)
    try:
        await msg.add_reaction('🍁')
    except discord.HTTPException:
        log.warning('Could not add maple leaf reaction to signup panel %s; signup buttons are still available.',msg.id,exc_info=True)
    await interaction.followup.send(f'Panel posted: {msg.jump_url}\\nPlayers can use the **Join Adventure** button even if reactions do not appear.',ephemeral=True)

@forest.command(name='dashboard',description='Host: monitor participation')
async def dashboard_cmd(interaction:discord.Interaction):
    if not await host_only(interaction): return
    rows=conn.execute("SELECT data FROM runs WHERE mode='main'").fetchall()
    states=[json.loads(r['data']) for r in rows]
    await interaction.response.send_message(f'Phase: **{phase()}** | Players: **{len(states)}** | Finished: **{sum(s["finished"] for s in states)}** | Tiebreaker: **{meta("tie_ids") or "None"}**',ephemeral=True)

@forest.command(name='logs',description='Host: view recent gameplay actions')
async def logs_cmd(interaction:discord.Interaction):
    if not await host_only(interaction): return
    rows=conn.execute('SELECT * FROM actions ORDER BY id DESC LIMIT 12').fetchall()
    txt='\n'.join(f'<@{r["uid"]}> {r["mode"]} #{r["step"]+1}: {r["result"]}' for r in rows) or 'No actions yet.'
    await interaction.response.send_message(txt[:1900],ephemeral=True)

@forest.command(name='audit',description='Host: check stored game state')
async def audit_cmd(interaction:discord.Interaction):
    if not await host_only(interaction): return
    rows=conn.execute('SELECT data FROM runs').fetchall()
    states=[json.loads(r['data']) for r in rows]
    bad=sum(not(0<=s['step']<=40 and 0<=s['hp']<=100 and 0<=s['en']<=100 and 0<=s['sup']<=12 and 0<=s['art']<=1000) for s in states)
    await interaction.response.send_message(f'Runs: {len(states)} | Invalid state bounds: {bad} | Action records: {conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]}\nThis cannot detect alternate accounts or outside help.',ephemeral=True)

def rankings():
    rows=conn.execute("SELECT uid,data FROM runs WHERE mode='main'").fetchall()
    out=[]
    for r in rows:
        s=json.loads(r['data'])
        if s['finished']:
            key=(s['score'],s['art'],s['objective'],s['hp']+s['en'])
            out.append((r['uid'],s,key))
    return sorted(out,key=lambda x:x[2],reverse=True)

@forest.command(name='leaderboard',description='View winners once the event is final')
async def leaderboard_cmd(interaction:discord.Interaction):
    if not meta('finalized'): return await interaction.response.send_message('Results are hidden until the competition and any tiebreakers finish.',ephemeral=True)
    rows=rankings(); ids=json.loads(meta('final_order') or '[]')
    scores={uid:s for uid,s,_ in rows}
    text='\n'.join(f'**{i+1}.** <@{uid}> — {scores[uid]["score"]:,} points' for i,uid in enumerate(ids[:10]) if uid in scores) or 'No eligible results.'
    await interaction.response.send_message(embed=discord.Embed(title='🏆 Forbidden Forest — Final Leaderboard',description=text,color=0xD6A64B))

# Prize-position exact ties are resolved by a separate identical 5-question strategic challenge.
BONUS_QUESTIONS=[
 ('A relic costs 2 supplies for 80 pts or 1 supply for 40 pts. Which has higher points per supply?', ['Same','80-point relic','40-point relic'],0),
 ('You have 15 energy. Two routes cost 9 and 7 energy. Can you take both without recovering?', ['Yes','No','Only with Guardian'],1),
 ('A potion heals 25 energy but you have 90/100 energy. How much energy can you gain?', ['25','10','0'],1),
 ('Three objectives award 100 points each. How many points for two?', ['200','150','300'],0),
 ('A 100-point artefact loses 25% on defeat. How many points remain?', ['50','75','80'],1),
]

class TieView(discord.ui.View):
    def __init__(self,uid,index):
        super().__init__(timeout=600)
        self.uid,self.index=uid,index
        for i,text in enumerate(BONUS_QUESTIONS[index][1]):
            b=discord.ui.Button(label=text,style=discord.ButtonStyle.primary)
            b.callback=self.answer(i)
            self.add_item(b)
    def answer(self,answer):
        async def cb(interaction):
            if interaction.user.id!=self.uid: return await interaction.response.send_message('Not your challenge.',ephemeral=True)
            if not END<=now()<BONUS_END: return await interaction.response.send_message('Tiebreaker is closed.',ephemeral=True)
            async with mutex:
                s=get_run(self.uid,'tie')
                if not s or s['step']!=self.index: return await interaction.response.send_message('Old question. Use `/forest tiebreaker`.',ephemeral=True)
                s['correct']+=int(answer==BONUS_QUESTIONS[self.index][2]); s['step']+=1
                save(self.uid,'tie',s)
            await show_tie(interaction,s)
        return cb

async def show_tie(interaction,s):
    if s['step']>=5:
        msg=f'🏆 Tiebreaker completed: **{s["correct"]}/5**. Results will be published after the deadline.'
        if interaction.response.is_done(): return await interaction.followup.send(msg,ephemeral=True)
        return await interaction.response.send_message(msg,ephemeral=True)
    q,answers,_=BONUS_QUESTIONS[s['step']]
    kwargs={'content':f'🏆 **Bonus challenge {s["step"]+1}/5**\n{q}','view':TieView(interaction.user.id,s['step']),'ephemeral':True}
    if interaction.response.is_done(): await interaction.followup.send(**kwargs)
    else: await interaction.response.send_message(**kwargs)

@forest.command(name='tiebreaker',description='Complete your prize-position tiebreaker if eligible')
async def tie_cmd(interaction:discord.Interaction):
    if not END<=now()<BONUS_END: return await interaction.response.send_message('No active tiebreaker window.',ephemeral=True)
    eligible=json.loads(meta('tie_ids') or '[]')
    if interaction.user.id not in eligible: return await interaction.response.send_message('You are not eligible for this tiebreaker.',ephemeral=True)
    async with mutex:
        s=get_run(interaction.user.id,'tie')
        if not s:
            s={'step':0,'correct':0}; save(interaction.user.id,'tie',s)
    await show_tie(interaction,s)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.guild_id!=GUILD or str(payload.message_id)!=meta('panel_message') or str(payload.emoji)!='🍁': return
    guild=bot.get_guild(GUILD)
    if not guild or payload.user_id==bot.user.id: return
    try:
        member=payload.member or await guild.fetch_member(payload.user_id)
        role=guild.get_role(ROLE)
        if role and not member.bot: await member.add_roles(role,reason='Forest 🍁 signup')
    except discord.HTTPException: log.exception('Unable to add event role')

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.guild_id!=GUILD or str(payload.message_id)!=meta('panel_message') or str(payload.emoji)!='🍁': return
    guild=bot.get_guild(GUILD)
    if not guild: return
    try:
        member=await guild.fetch_member(payload.user_id); role=guild.get_role(ROLE)
        if role and not member.bot: await member.remove_roles(role,reason='Forest 🍁 signup removed')
    except discord.HTTPException: log.exception('Unable to remove event role')

async def channel():
    c=bot.get_channel(CHANNEL)
    if c: return c
    try: return await bot.fetch_channel(CHANNEL)
    except discord.HTTPException: return None

async def reconcile():
    async with mutex:
        t=now()
        if START<=t<END and not meta('opened'):
            c=await channel()
            if c:
                await c.send(content=f'<@&{ROLE}> 🌲 **THE FORBIDDEN FOREST IS OPEN!**',embed=discord.Embed(description='40 encounters await. Use `/forest official` for your one prize-eligible adventure. Ends **11 November at 00:00 GMT**.',color=0xAA743A),view=EntryView(),allowed_mentions=discord.AllowedMentions(roles=True))
                set_meta('opened','1')
        if t>=END and not meta('closed'):
            rows=conn.execute("SELECT uid,data FROM runs WHERE mode='main'").fetchall()
            for row in rows:
                s=json.loads(row['data'])
                if not s['finished']:
                    finish(s,False); save(row['uid'],'main',s)
            ordered=rankings()
            groups={}
            for uid,s,key in ordered: groups.setdefault(key,[]).append(uid)
            eligible=[]; rank=1
            for key in sorted(groups,reverse=True):
                ids=groups[key]
                if rank<=3 and len(ids)>1: eligible.extend(ids)
                rank+=len(ids)
            set_meta('tie_ids',json.dumps(eligible))
            set_meta('closed','1')
            c=await channel()
            if c:
                if eligible:
                    await c.send(content=' '.join(f'<@{uid}>' for uid in eligible)[:1800],embed=discord.Embed(title='🏆 Prize-position tiebreaker',description='Eligible players: use `/forest tiebreaker` for 5 identical strategic questions before **12 Nov 00:00 GMT**. No speed scoring.',color=0xD5A64B),allowed_mentions=discord.AllowedMentions(users=True))
                else:
                    await finalize(c)
        if t>=BONUS_END and not meta('finalized'):
            await finalize(await channel())

async def finalize(c):
    if meta('finalized'): return
    rows=rankings(); eligible=set(json.loads(meta('tie_ids') or '[]'))
    # Public predetermined final fallback: deterministic SHA256 of user ID and fixed event string.
    def key(row):
        uid,s,mainkey=row
        tie=get_run(uid,'tie') or {'correct':-1}
        bonus=tie['correct'] if uid in eligible else -1
        fallback=int(hashlib.sha256(f'forest-2026-final|{uid}'.encode()).hexdigest(),16)
        return (mainkey,bonus,fallback)
    rows.sort(key=key,reverse=True)
    order=[uid for uid,_,_ in rows]
    set_meta('final_order',json.dumps(order)); set_meta('finalized','1')
    if c:
        prizes=['125c + HC Box','75c + HC Box','50c + HC Box']
        body='\n'.join(f'**{i+1}.** <@{uid}> — **{s["score"]:,}** points — {prizes[i]}' for i,(uid,s,_) in enumerate(rows[:3])) or 'No completed adventures.'
        await c.send(embed=discord.Embed(title='🏆 Forbidden Forest — Winners',description=body,color=0xD5A64B))

@tasks.loop(seconds=30)
async def scheduler():
    try: await reconcile()
    except Exception: log.exception('Scheduled transition failed')

@scheduler.before_loop
async def before_scheduler(): await bot.wait_until_ready()

@bot.event
async def setup_hook():
    db_init(); bot.add_view(EntryView()); bot.add_view(SignupView())
    bot.tree.add_command(forest,guild=discord.Object(id=GUILD))
    await bot.tree.sync(guild=discord.Object(id=GUILD))
    scheduler.start()

@bot.event
async def on_ready(): log.info('Ready as %s; phase=%s',bot.user,phase())

if __name__=='__main__':
    if not TOKEN or not GUILD or not CHANNEL: raise RuntimeError('Set DISCORD_TOKEN, GUILD_ID, EVENT_CHANNEL_ID')
    bot.run(TOKEN)
