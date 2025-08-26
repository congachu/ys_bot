# role.py
import discord
from discord import app_commands
from discord.ext import commands

from os import getenv
ADMIN_ID = int(getenv("ADMIN_ID", "0"))

class RoleSetting(commands.Cog):
    """
    관리 명령 사용 가능 '역할' 화이트리스트 관리
    - /관리자역할추가 <역할>
    - /관리자역할삭제 <역할>
    - /관리자역할확인
    DB: admin_allowed_role(role_id BIGINT PRIMARY KEY)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._create_table()

    # ---------- 공통: 거부/오류는 에페메럴 텍스트 ----------
    async def _deny(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)

    # ---------- DB ----------
    def _create_table(self) -> None:
        cur = self.bot.cursor
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_allowed_role (
            role_id BIGINT PRIMARY KEY
        )
        """)
        self.bot.conn.commit()

    # 공개 헬퍼: 멤버가 허용 역할을 하나라도 가지고 있는가
    async def user_has_manager_role(self, member: discord.Member) -> bool:
        cur = self.bot.cursor
        cur.execute("SELECT role_id FROM admin_allowed_role")
        rows = cur.fetchall()
        if not rows:
            return False  # 등록된 역할이 없으면 False (ADMIN_ID/관리자 권한은 외부에서 별도로 체크)
        allowed_ids = {rid for (rid,) in rows}
        return any((r.id in allowed_ids) for r in member.roles)

    # ---------- 권한 체크(역할/서버 관리자 중 하나) ----------
    async def _can_manage_roles(self, interaction: discord.Interaction) -> bool:
        # 서버 관리자 권한 or 이미 허용 역할을 가진 경우 허용
        if interaction.user.guild_permissions.administrator or interaction.user.id == ADMIN_ID:
            return True
        await self._deny(interaction, "⚠️ 이 명령은 **관리자 권한**이 필요해요.")
        return False

    # ---------- 명령어들 ----------
    @app_commands.command(name="관리자역할추가", description="관리자 명령 사용 가능 역할을 추가합니다.")
    async def add_manager_role(self, interaction: discord.Interaction, 역할: discord.Role):
        if not await self._can_manage_roles(interaction):
            return

        cur = self.bot.cursor
        try:
            cur.execute(
                "INSERT INTO admin_allowed_role (role_id) VALUES (%s) ON CONFLICT (role_id) DO NOTHING",
                (역할.id,)
            )
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 역할 추가 중 오류가 발생했어요.")
            return

        embed = discord.Embed(
            title="❄️ 관리자 역할 추가",
            description=f"{역할.mention} 역할이 **관리자 명령 허용 역할**로 등록되었습니다.",
            color=discord.Color.teal()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="관리자역할삭제", description="관리자 명령 사용 가능 역할을 제거합니다.")
    async def remove_manager_role(self, interaction: discord.Interaction, 역할: discord.Role):
        if not await self._can_manage_roles(interaction):
            return

        cur = self.bot.cursor
        try:
            cur.execute("DELETE FROM admin_allowed_role WHERE role_id = %s", (역할.id,))
            self.bot.conn.commit()
        except Exception:
            self.bot.conn.rollback()
            await self._deny(interaction, "⚠️ 역할 삭제 중 오류가 발생했어요.")
            return

        embed = discord.Embed(
            title="🌨️ 관리자 역할 삭제",
            description=f"{역할.mention} 역할이 **관리자 명령 허용 역할**에서 제거되었습니다.",
            color=discord.Color.dark_blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="관리자역할확인", description="등록된 관리자 명령 허용 역할 목록을 확인합니다.")
    async def list_manager_roles(self, interaction: discord.Interaction):
        if not await self._can_manage_roles(interaction):
            return
        cur = self.bot.cursor
        cur.execute("SELECT role_id FROM admin_allowed_role ORDER BY role_id")
        rows = cur.fetchall()

        embed = discord.Embed(
            title="⛄ 관리자 명령 허용 역할",
            color=discord.Color.blue()
        )
        if not rows:
            embed.description = "등록된 역할이 없습니다."
        else:
            desc_lines = []
            for (rid,) in rows:
                role = interaction.guild.get_role(rid)
                if role:
                    desc_lines.append(f"• {role.mention} (`{rid}`)")
                else:
                    desc_lines.append(f"• (서버에 없음) `{rid}`")
            embed.description = "\n".join(desc_lines)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleSetting(bot))
