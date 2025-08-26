import os
import asyncio
import datetime
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class AClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # Server Members Intent 사용

        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.start_time = datetime.datetime.now()  # 업타임 기준 시각
        self.setup_db_connection()

    # --------- 유틸 ----------
    @staticmethod
    def format_uptime(delta: datetime.timedelta) -> str:
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"

    async def setup_hook(self):
        # 코그 로드
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await self.load_extension(f"cogs.{filename[:-3]}")

        # 슬래시 동기화 1회
        if not self.synced:
            await self.tree.sync()
            self.synced = True

        # 상태 업데이트를 백그라운드 태스크로 시작
        self.loop.create_task(self.update_status())

        print("✅ 준비 완료")

    async def on_ready(self):
        print(f"✅ {self.user} 로그인 완료")

    # --------- DB ----------
    def setup_db_connection(self):
        try:
            self.conn = psycopg2.connect(
                dbname=os.getenv("DB_NAME"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=os.getenv("DB_HOST"),
                sslmode='prefer',
                connect_timeout=10,
            )
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
        except Exception as e:
            print(f"❌ 데이터베이스 연결 오류: {e}")
            self.conn, self.cursor = None, None

    def ensure_db_connection(self):
        try:
            if not self.conn or self.conn.closed:
                print("⚠️ 데이터베이스 재연결 시도 중...")
                self.setup_db_connection()
            return self.conn is not None
        except Exception as e:
            print(f"❌ 데이터베이스 상태 확인 중 오류: {e}")
            return False

    def get_cursor(self):
        """데이터베이스 연결을 확인하고 커서 반환"""
        if self.ensure_db_connection():
            return self.conn.cursor()
        return None

    # --------- 상태 메시지: 업타임 ---------
    async def update_status(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                uptime = datetime.datetime.now() - self.start_time
                text = f"⏱️ Uptime: {self.format_uptime(uptime)}"
                await self.change_presence(activity=discord.Game(text))
                await asyncio.sleep(60)  # 1분마다 업데이트
            except Exception as e:
                print(f"❌ 상태 업데이트 오류: {e}")
                await asyncio.sleep(5)

client = AClient()

try:
    client.run(os.getenv("DISCORD_TOKEN"))
except KeyboardInterrupt:
    print("🛑 봇이 중지되었습니다.")
except Exception as e:
    print(f"❌ 봇 실행 중 오류 발생: {e}")
