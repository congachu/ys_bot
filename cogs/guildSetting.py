import discord
from discord import app_commands
from discord.ext import commands


class GuildSetting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def setup_allowed_channels_table(self):
        """단일 서버: 허용 채널 여러 개 관리"""
        cursor = None
        try:
            cursor = self.bot.get_cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_allowed_channel (
                    channel_id BIGINT PRIMARY KEY
                )
            """)
            self.bot.conn.commit()
        except Exception as e:
            self.bot.conn.rollback()
            print(f"테이블 생성 중 오류: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    # --- 관리 명령어들 ---

    @app_commands.command(name="채널추가", description="현재 채널을 봇 명령어 허용 채널로 추가합니다.")
    async def add_channel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        cursor = None
        try:
            cursor = self.bot.get_cursor()
            await self.setup_allowed_channels_table()

            cursor.execute("""
                INSERT INTO bot_allowed_channel (channel_id)
                VALUES (%s)
                ON CONFLICT (channel_id) DO NOTHING
            """, (interaction.channel.id,))
            self.bot.conn.commit()

            await interaction.response.send_message(
                f"{interaction.channel.mention} 채널이 **허용 채널**로 추가되었습니다.", ephemeral=True
            )
        except Exception as e:
            self.bot.conn.rollback()
            print(f"채널 추가 중 오류: {e}")
            await interaction.response.send_message("채널 추가 중 오류가 발생했습니다.", ephemeral=True)
        finally:
            if cursor:
                cursor.close()

    @app_commands.command(name="채널삭제", description="현재 채널을 봇 명령어 허용 채널에서 제거합니다.")
    async def remove_channel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        cursor = None
        try:
            cursor = self.bot.get_cursor()
            await self.setup_allowed_channels_table()

            cursor.execute("DELETE FROM bot_allowed_channel WHERE channel_id = %s",
                           (interaction.channel.id,))
            self.bot.conn.commit()

            await interaction.response.send_message(
                f"{interaction.channel.mention} 채널이 **허용 채널**에서 제거되었습니다.", ephemeral=True
            )
        except Exception as e:
            self.bot.conn.rollback()
            print(f"채널 삭제 중 오류: {e}")
            await interaction.response.send_message("채널 삭제 중 오류가 발생했습니다.", ephemeral=True)
        finally:
            if cursor:
                cursor.close()

    @app_commands.command(name="채널확인", description="현재 설정된 봇 명령어 허용 채널 목록을 확인합니다.")
    async def list_channels(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        cursor = None
        try:
            cursor = self.bot.get_cursor()
            await self.setup_allowed_channels_table()

            cursor.execute("SELECT channel_id FROM bot_allowed_channel ORDER BY channel_id")
            rows = cursor.fetchall()

            if not rows:
                await interaction.response.send_message("설정된 허용 채널이 없습니다.", ephemeral=True)
                return

            embed = discord.Embed(title="봇 명령어 허용 채널 목록", color=discord.Color.blue())
            for (cid,) in rows:
                ch = interaction.guild.get_channel(cid)
                value = ch.mention if isinstance(ch, discord.TextChannel) else f"(삭제되었거나 접근 불가) {cid}"
                embed.add_field(name="·", value=value, inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"채널 확인 중 오류: {e}")
            await interaction.response.send_message("채널 확인 중 오류가 발생했습니다.", ephemeral=True)
        finally:
            if cursor:
                cursor.close()

    # --- 사용 권한 체크 헬퍼 ---

    async def check_channel_permission(self, interaction: discord.Interaction) -> bool:
        """
        허용 채널이 하나도 없으면 모든 채널 허용.
        하나 이상 있으면, 현재 채널이 목록에 포함될 때만 허용.
        """
        cursor = None
        try:
            cursor = self.bot.get_cursor()
            cursor.execute("SELECT channel_id FROM bot_allowed_channel")
            rows = cursor.fetchall()

            if not rows:
                return True  # 설정이 없으면 전체 허용

            allowed = {cid for (cid,) in rows}
            return interaction.channel.id in allowed

        except Exception as e:
            print(f"권한 확인 중 오류: {e}")
            return False
        finally:
            if cursor:
                cursor.close()


async def setup(bot):
    await bot.add_cog(GuildSetting(bot))
