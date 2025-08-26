import os
import asyncio
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class AClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()  # 기본 인텐트만 활성화
        intents.members = True  # 승인된 'Server Members Intent' 활성화

        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.setup_db_connection()

    async def setup_hook(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await self.load_extension(f"cogs.{filename[:-3]}")
        if not self.synced:
            await self.tree.sync()
            self.synced = True
        print("✅ 준비 완료")

    async def on_ready(self):
        await self.update_status()
        print(f"✅ {self.user} 로그인 완료")

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
        if self.ensure_db_connection():  # ensure_db_connection()이 False면 None을 반환
            return self.conn.cursor()
        return None  # 연결이 없으면 None 반환

    async def update_status(self):
        while True:
            try:
                ping = round(self.latency * 1000)

                await self.change_presence(
                    activity=discord.Game(f"현재 핑: {ping}ms")
                )
                await asyncio.sleep(60)  # 10분마다 업데이트
            except Exception as e:
                print(f"❌ 상태 업데이트 오류: {e}")

client = AClient()

try:
    client.run(os.getenv("DISCORD_TOKEN"))
except KeyboardInterrupt:
    print("🛑 봇이 중지되었습니다.")
except Exception as e:
    print(f"❌ 봇 실행 중 오류 발생: {e}")