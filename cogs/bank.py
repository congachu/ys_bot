# bank.py (거부/오류 메시지: 에페메럴 텍스트 통일)

import datetime
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from typing import List, Tuple

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

class Bank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self._create_or_migrate_tables()

        # 1분마다 보이스 보상
        self.scheduler.add_job(self.pay_voice_rewards, "interval", minutes=1, max_instances=1, coalesce=True)

    # ---------- 공통 헬퍼 ----------
    async def _deny(self, interaction: discord.Interaction, text: str) -> None:
        """모든 거부/오류/쿨타임/권한 부족 메시지는 이걸로 (에페메럴 텍스트)"""
        await interaction.response.send_message(text, ephemeral=True)

    # ---------- DB ----------
    def _create_or_migrate_tables(self) -> None:
        cur = self.bot.cursor
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uuid BIGINT PRIMARY KEY,
            money BIGINT DEFAULT 0,
            last_sobok TIMESTAMP NULL,
            last_chat_reward_at TIMESTAMP NULL
        )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_sobok TIMESTAMP NULL")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_chat_reward_at TIMESTAMP NULL")
        self.bot.conn.commit()

    async def ensure_user(self, user_id: int) -> None:
        cur = self.bot.cursor
        cur.execute("SELECT 1 FROM users WHERE uuid=%s", (user_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (uuid) VALUES (%s)", (user_id,))
            self.bot.conn.commit()

    # ---------- 채널 체크 ----------
    async def check_bot_channel(self, interaction: discord.Interaction) -> bool:
        settings_cog = self.bot.get_cog("GuildSetting")
        if settings_cog is None:
            return True
        allowed = await settings_cog.check_channel_permission(interaction)
        if not allowed:
            await self._deny(interaction, "🚫 이 채널에서는 명령어를 사용할 수 없어요.")
            return False
        return True

    # ---------- 관리자 체크 ----------
    async def check_admin(self, interaction: discord.Interaction) -> bool:
        # 1) ENV ADMIN_ID or 서버 관리자
        if interaction.user.id == ADMIN_ID or interaction.user.guild_permissions.administrator:
            return True
        # 2) 등록된 관리 역할 보유 여부
        role_cog = self.bot.get_cog("RoleSetting")
        if role_cog and await role_cog.user_has_manager_role(interaction.user):
            return True
        # 거부 = 에페메럴 텍스트
        await self._deny(interaction, "⚠️ 이 명령어는 **관리 권한**이 필요해요.")
        return False

    # ---------- 명령어 ----------
    @app_commands.command(name="지갑", description="령 잔액을 확인합니다.")
    async def cmd_wallet(self, interaction: discord.Interaction, 사용자: discord.Member = None):
        if not await self.check_bot_channel(interaction):
            return

        member = 사용자 or interaction.user
        await self.ensure_user(member.id)

        cur = self.bot.cursor
        cur.execute("SELECT money FROM users WHERE uuid=%s", (member.id,))
        bal = cur.fetchone()[0]

        # 성공 메시지는 겨울 테마 임베드 유지
        embed = discord.Embed(
            title="지갑 🎐",
            description=f"서리가 남긴 맑은 소리 , **{bal:,}령**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="송금", description="다른 사용자에게 nn령을 송금합니다.")
    async def cmd_send(self, interaction: discord.Interaction, 대상: discord.Member, 금액: int):
        if not await self.check_bot_channel(interaction):
            return
        if 금액 <= 0:
            await self._deny(interaction, "❌ 송금 금액은 **1 이상**이어야 해요.")
            return

        sender = interaction.user
        receiver = 대상
        await self.ensure_user(sender.id)
        await self.ensure_user(receiver.id)

        cur = self.bot.cursor
        cur.execute("SELECT money FROM users WHERE uuid=%s", (sender.id,))
        sender_money = cur.fetchone()[0]

        if sender_money < 금액:
            await self._deny(interaction, "❌ 잔액이 부족해요.")
            return

        try:
            cur.execute("UPDATE users SET money = money - %s WHERE uuid=%s", (금액, sender.id))
            cur.execute("UPDATE users SET money = money + %s WHERE uuid=%s", (금액, receiver.id))
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 송금 처리 중 문제가 발생했어요.")
            return

        embed = discord.Embed(
            title="송금 ☃️",
            description=f"쓰지 못해 미룬 마음, **{금액:,}령**\n\n{sender.mention} ➝ {receiver.mention}",
            color=discord.Color.teal()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="지급", description="관리진 전용: 대상(또는 역할 전체)에게 nn령 지급합니다.")
    async def cmd_grant(
            self,
            interaction: discord.Interaction,
            금액: int,
            사유: str,
            대상: discord.Member | None = None,
            역할: discord.Role | None = None,
    ):
        if not await self.check_bot_channel(interaction):
            return
        if not await self.check_admin(interaction):
            return
        if 금액 <= 0:
            await self._deny(interaction, "❌ 지급 금액은 **1 이상**이어야 해요.")
            return

        # 대상/역할 검증
        if (대상 is None and 역할 is None) or (대상 is not None and 역할 is not None):
            await self._deny(interaction, "⚠️ `대상` **또는** `역할` 중 하나만 지정해주세요.")
            return

        cur = self.bot.cursor

        # 개별 사용자 지급
        if 대상 is not None:
            await self.ensure_user(대상.id)
            try:
                cur.execute("UPDATE users SET money = money + %s WHERE uuid=%s", (금액, 대상.id))
                self.bot.conn.commit()
            except Exception:
                self.bot.conn.rollback()
                await self._deny(interaction, "⚠️ 지급 처리 중 문제가 발생했어요.")
                return

            cur.execute("SELECT money FROM users WHERE uuid=%s", (대상.id,))
            bal = cur.fetchone()[0]

            desc = f"{대상.mention} **{금액:,}령** 지급되었습니다.\n잔액: **{bal:,}령**"
            if 사유:
                desc += f"\n\n📝 사유: {discord.utils.escape_markdown(사유)}"

            embed = discord.Embed(
                title="지급 💎",
                description=desc,
                color=discord.Color.teal(),
            )
            await interaction.response.send_message(embed=embed)
            return

        # 역할 전체 지급
        members = [m for m in interaction.guild.members if (역할 in m.roles) and (not m.bot)]
        if not members:
            await self._deny(interaction, "⚠️ 해당 역할을 가진 **사람**(봇 제외)이 없어요.")
            return

        # 사용자 보장 + 일괄 지급
        try:
            for m in members:
                await self.ensure_user(m.id)
            params = [(금액, m.id) for m in members]
            # executemany로 일괄 업데이트
            cur.executemany("UPDATE users SET money = money + %s WHERE uuid=%s", params)
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 역할 지급 처리 중 문제가 발생했어요.")
            return

        총인원 = len(members)
        총액 = 금액 * 총인원
        desc = f"{역할.mention} 역할 구성원 **{총인원}명**에게 각 **{금액:,}령** 지급 완료.\n총 지급: **{총액:,}령**"
        if 사유:
            desc += f"\n\n📝 사유: {discord.utils.escape_markdown(사유)}"

        embed = discord.Embed(
            title="지급 💎",
            description=desc,
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="회수", description="관리진 전용: 대상(또는 역할 전체)에게서 nn령 회수합니다.")
    async def cmd_withdraw(
            self,
            interaction: discord.Interaction,
            금액: int,
            사유: str,
            대상: discord.Member | None = None,
            역할: discord.Role | None = None,
    ):
        if not await self.check_bot_channel(interaction):
            return
        if not await self.check_admin(interaction):
            return
        if 금액 <= 0:
            await self._deny(interaction, "❌ 회수 금액은 **1 이상**이어야 해요.")
            return

        if (대상 is None and 역할 is None) or (대상 is not None and 역할 is not None):
            await self._deny(interaction, "⚠️ `대상` **또는** `역할` 중 하나만 지정해주세요.")
            return

        cur = self.bot.cursor

        # 개별 사용자 회수
        if 대상 is not None:
            await self.ensure_user(대상.id)
            try:
                cur.execute("UPDATE users SET money = GREATEST(money - %s, 0) WHERE uuid=%s", (금액, 대상.id))
                self.bot.conn.commit()
            except Exception:
                self.bot.conn.rollback()
                await self._deny(interaction, "⚠️ 회수 처리 중 문제가 발생했어요.")
                return

            cur.execute("SELECT money FROM users WHERE uuid=%s", (대상.id,))
            bal = cur.fetchone()[0]

            desc = f"{대상.mention} **{금액:,}령** 회수되었습니다.\n잔액: **{bal:,}령**"
            if 사유:
                desc += f"\n\n📝 사유: {discord.utils.escape_markdown(사유)}"

            embed = discord.Embed(
                title="회수 💧",
                description=desc,
                color=discord.Color.dark_blue(),
            )
            await interaction.response.send_message(embed=embed)
            return

        # 역할 전체 회수
        members = [m for m in interaction.guild.members if (역할 in m.roles) and (not m.bot)]
        if not members:
            await self._deny(interaction, "⚠️ 해당 역할을 가진 **사람**(봇 제외)이 없어요.")
            return

        try:
            for m in members:
                await self.ensure_user(m.id)
            params = [(금액, m.id) for m in members]
            cur.executemany("UPDATE users SET money = GREATEST(money - %s, 0) WHERE uuid=%s", params)
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 역할 회수 처리 중 문제가 발생했어요.")
            return

        총인원 = len(members)
        총액_명목 = 금액 * 총인원  # 실제로는 GREATEST로 인해 총 회수액이 이보다 적을 수 있음
        desc = (
            f"{역할.mention} 역할 구성원 **{총인원}명**에게서 각 **{금액:,}령** 회수 시도 완료.\n"
            f"명목상 최대 회수: **{총액_명목:,}령**"
        )
        if 사유:
            desc += f"\n\n📝 사유: {discord.utils.escape_markdown(사유)}"

        embed = discord.Embed(
            title="회수 💧",
            description=desc,
            color=discord.Color.dark_blue(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="소복", description="랜덤(1~100령) 지급 / 30분 쿨타임")
    async def cmd_sobok(self, interaction: discord.Interaction):
        if not await self.check_bot_channel(interaction):
            return

        user = interaction.user
        await self.ensure_user(user.id)

        cur = self.bot.cursor
        cur.execute("SELECT money, last_sobok FROM users WHERE uuid=%s", (user.id,))
        money, last_sobok = cur.fetchone()
        now = datetime.datetime.now()
        cooldown = 30 * 60

        if last_sobok and (now - last_sobok).total_seconds() < cooldown:
            remain = cooldown - (now - last_sobok).total_seconds()
            m, s = int(remain // 60), int(remain % 60)
            await self._deny(interaction, f"⏳ {m}분 {s}초 후에 다시 사용할 수 있어요.")
            return

        reward = random.randint(1, 100)
        try:
            cur.execute(
                "UPDATE users SET money = money + %s, last_sobok = %s WHERE uuid=%s",
                (reward, now, user.id)
            )
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 소복 사용 중 문제가 발생했어요.")
            return

        embed = discord.Embed(
            title="소복 ❄️",
            description=(
                "소복소복 , 눈이 내리는 날 .\n"
                "맑은 방울 소리가 아련히 들려옵니다.\n\n"
                f"{user.mention} **{reward}령** 지급 완료"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="순위", description="보유 금액 상위 10명을 보여줍니다.")
    async def cmd_leaderboard(self, interaction: discord.Interaction):
        if not await self.check_bot_channel(interaction):
            return

        user = interaction.user
        await self.ensure_user(user.id)

        cur = self.bot.cursor
        try:
            # 상위 10명
            cur.execute("""
                SELECT uuid, money
                FROM users
                ORDER BY money DESC, uuid ASC
                LIMIT 10
            """)
            top = cur.fetchall()

            # 내 순위
            cur.execute("""
                SELECT rnk, money FROM (
                  SELECT uuid, money, RANK() OVER (ORDER BY money DESC, uuid ASC) AS rnk
                  FROM users
                ) t
                WHERE uuid = %s
            """, (user.id,))
            me = cur.fetchone()
            my_rank = me[0] if me else None
            my_money = me[1] if me else 0

        except Exception:
            await self._deny(interaction, "⚠️ 순위를 불러오는 중 문제가 발생했어요.")
            return

        # TOP 10 리스트 작성
        lines = []
        for idx, (uid, money) in enumerate(top, start=1):
            member = interaction.guild.get_member(uid)
            name = member.mention if member else f"(탈퇴/미확인) `{uid}`"
            lines.append(f"{idx}. {name} — {money:,}령")

        desc = "보유한 **령** 기준 상위 10명\n\n" + "\n".join(lines)

        # 내가 10위 밖일 경우, 맨 아래에 내 순위 추가
        if my_rank and my_rank > 10:
            desc += f"\n\n내 순위: {my_rank}위 • 보유: {my_money:,}령"

        embed = discord.Embed(
            title="랭킹",
            description=desc,
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed)

    # ---------- 채팅 보상 ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 화이트리스트 무관하게 전역 적용 (변경 없음)
        if message.author.bot or message.guild is None:
            return

        user = message.author
        await self.ensure_user(user.id)

        cur = self.bot.cursor
        cur.execute("SELECT last_chat_reward_at FROM users WHERE uuid=%s", (user.id,))
        last = cur.fetchone()[0]
        now = datetime.datetime.now()

        if last and (now - last).total_seconds() < 60:
            return  # 1분 쿨타임

        try:
            cur.execute(
                "UPDATE users SET money = money + %s, last_chat_reward_at = %s WHERE uuid=%s",
                (2, now, user.id)
            )
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()

    # ---------- 통화 보상 ----------
    async def pay_voice_rewards(self):
        try:
            to_pay = []
            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    for member in vc.members:
                        if not member.bot:
                            to_pay.append(member.id)

            if not to_pay:
                return

            cur = self.bot.cursor
            for uid in set(to_pay):
                await self.ensure_user(uid)
                cur.execute("UPDATE users SET money = money + 3 WHERE uuid=%s", (uid,))
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()

async def setup(bot: commands.Bot):
    await bot.add_cog(Bank(bot))
