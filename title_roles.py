"""Manage only zero-permission title roles created by this bot."""
import asyncio
import logging
import discord

from database import MemoryUnavailable
from title_notifications import title_icon
from title_core import is_retired_title


class TitleRoles:
    def __init__(self, store):
        self.store = store
        self.locks = {}

    def lock(self, guild_id):
        return self.locks.setdefault(guild_id, asyncio.Lock())

    @staticmethod
    def check_bot(guild):
        if not guild.me or not guild.me.guild_permissions.manage_roles:
            raise ValueError('ジョージに「ロールの管理」権限が必要だぜ。管理者に確認してくれ！')

    @staticmethod
    def bot_top(guild, roles):
        ids = {role.id for role in getattr(guild.me, 'roles', ())}
        return max((role for role in roles if role.id in ids), key=lambda role: role.position, default=guild.me.top_role)

    @staticmethod
    def safe_role(guild, role, top=None):
        if role.managed or role.is_default() or role >= (top or guild.me.top_role):
            raise ValueError('称号ロールはジョージのロールより下に置いてくれ！')
        if role.permissions.value or role.colour.value or role.hoist or role.mentionable:
            raise ValueError('称号ロールの設定が変更されているぜ。権限・色なし、メンバー分離・メンションOFFに戻してくれ。')

    async def retire_exchange(self, guild):
        async with self.lock(guild.id):
            mapping = await asyncio.to_thread(self.store.role_map, guild.id)
            role_id = mapping.get('exchange10')
            if role_id is None:
                return
            roles = await guild.fetch_roles()
            role = next((role for role in roles if role.id == role_id), None)
            if role is not None:
                self.check_bot(guild)
                self.safe_role(guild, role, self.bot_top(guild, roles))
                await role.delete(reason='廃止された交換称号を削除')
            await asyncio.to_thread(self.store.retire_exchange, guild.id, role_id)

    async def retire_collections(self, guild):
        async with self.lock(guild.id):
            mapping = await asyncio.to_thread(self.store.role_map, guild.id)
            retired = {key: role_id for key, role_id in mapping.items() if key.startswith('collection:')}
            if not retired:
                return
            roles = await guild.fetch_roles()
            for key, role_id in retired.items():
                role = next((role for role in roles if role.id == role_id), None)
                if role is not None:
                    self.check_bot(guild)
                    self.safe_role(guild, role, self.bot_top(guild, roles))
                    await role.delete(reason='廃止されたカード収集称号を削除')
                await asyncio.to_thread(self.store.retire_collection, guild.id, key, role_id)

    async def retire_removed(self, guild):
        async with self.lock(guild.id):
            mapping = await asyncio.to_thread(self.store.role_map, guild.id)
            retired = {key: role_id for key, role_id in mapping.items() if is_retired_title(key) and key != 'exchange10' and not key.startswith('collection:')}
            if not retired:
                return
            roles = await guild.fetch_roles()
            for key, role_id in retired.items():
                try:
                    role = next((role for role in roles if role.id == role_id), None)
                    if role is not None:
                        self.check_bot(guild)
                        self.safe_role(guild, role, self.bot_top(guild, roles))
                        await role.delete(reason='廃止された称号を削除')
                    await asyncio.to_thread(self.store.retire_title, guild.id, key, role_id)
                except (MemoryUnavailable, ValueError, discord.HTTPException) as exc:
                    logging.warning('Retired title cleanup failed: guild=%s type=%s', guild.id, type(exc).__name__)

    async def equip(self, guild, user_id, key=None):
        async with self.lock(guild.id):
            self.check_bot(guild)
            name = None
            if key is not None:
                titles = await asyncio.to_thread(self.store.titles, user_id)
                name = next((row[1] for row in titles if row[0] == key), None)
                if name is None:
                    raise ValueError('まだ獲得していない称号は装着できないぜ！')
            mapping = await asyncio.to_thread(self.store.role_map, guild.id)
            roles = {role.id: role for role in await guild.fetch_roles()}
            target = roles.get(mapping.get(key)) if key else None
            if key and target is None:
                target = await guild.create_role(name=f'{title_icon(key)} {name}'[:100], permissions=discord.Permissions.none(),
                    colour=discord.Colour.default(), hoist=False, mentionable=False, reason='ジョージの獲得済み称号')
                try:
                    bound = await asyncio.to_thread(self.store.bind_role, guild.id, key, target.id, mapping.get(key))
                except MemoryUnavailable:
                    try:
                        await target.delete(reason='称号ロールの保存失敗を取り消し')
                    except discord.HTTPException:
                        logging.warning('Title role cleanup failed')
                    raise
                if bound != target.id:
                    await target.delete(reason='同時作成された称号ロールを整理')
                    target = next((role for role in await guild.fetch_roles() if role.id == bound), None)
                    if target is None:
                        raise ValueError('称号ロールの更新中だぜ。少し待ってもう一度試してくれ！')
                mapping[key] = target.id
                # Role creation can move the bot's role before Gateway caches catch up.
                roles = {role.id: role for role in await guild.fetch_roles()}
                target = roles.get(target.id, target)
            top = self.bot_top(guild, roles.values())
            if target:
                self.safe_role(guild, target, top)
                role_name = f'{title_icon(key)} {name}'[:100]
                if target.name != role_name:
                    await target.edit(name=role_name, reason='称号ロールのマークを更新')
            member = await guild.fetch_member(user_id)
            ids = set(mapping.values())
            old = [roles.get(role.id, role) for role in member.roles if role.id in ids and (target is None or role.id != target.id)]
            for role in old:
                self.safe_role(guild, role, top)
            removed = []
            added = False
            try:
                for role in old:
                    await member.remove_roles(role, reason='ジョージの称号を変更', atomic=True)
                    removed.append(role)
                if target and target.id not in {r.id for r in member.roles}:
                    await member.add_roles(target, reason='ジョージの称号を装着', atomic=True)
                    added = True
                await asyncio.to_thread(self.store.save_equipped, guild.id, user_id, key, target.id if target else None)
            except (discord.HTTPException, MemoryUnavailable):
                try:
                    if added:
                        await member.remove_roles(target, reason='称号変更の失敗を取り消し', atomic=True)
                    for role in removed:
                        # Never restore a role whose privileges were changed by an administrator.
                        self.safe_role(guild, role, top)
                        await member.add_roles(role, reason='称号変更前に戻す', atomic=True)
                except (discord.HTTPException, ValueError):
                    logging.warning('Title role rollback failed')
                raise
            return name
