async def require_administrator(interaction):
    if interaction.guild_id is None or not interaction.permissions.administrator:
        await interaction.response.send_message('サーバーの管理者権限が必要だぜ。', ephemeral=True)
        return False
    return True
