import asyncio
import io
import json
import os
import re
import threading
import time
from functools import wraps
from textwrap import dedent

import discord
from discord.ext import commands

from config import config_ini
from cooldown import Cooldown
from gemini import Gemini, build_content_data
from history import HistoryHandler, change_position, to_jsonable
from import_checker import check_history

intents = discord.Intents.all()
bot = commands.Bot(intents=intents, command_prefix='.', help_command=None)
gemini = Gemini()

TOKEN = config_ini['MAIN']['BotToken']
TOKEN_DEV = config_ini['MAIN']['BotTokenDev']
HISTORY_FOLDER = config_ini['MAIN']['HistoryFolder']
CONFIG_FOLDER = config_ini['MAIN']['ConfigFolder']
DEFAULT_GEMINI_MODEL = config_ini['MAIN']['GeminiModel']
KEYS = config_ini['MAIN']['GeminiToken'].split(',')

chatname_compile = re.compile(r'\w+')
CONFIG_FORMAT = CONFIG_FOLDER + '/{}.json'
history_handler = HistoryHandler(HISTORY_FOLDER)


class Config:
    @staticmethod
    def load(name, default, int_keys = False):
        path = CONFIG_FORMAT.format(name)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                config = json.load(f)
                if int_keys:
                    config = {int(k): v for k, v in config.items()}
                return config
        return default

    @staticmethod
    def save(name, obj):
        with open(CONFIG_FORMAT.format(name), 'w', encoding='utf-8') as f:
            json.dump(obj, f)


class restrict:
    @staticmethod
    def mod_only(fn):
        @wraps(fn)
        async def wrapper(ctx: commands.Context, *args, **kwargs):
            if ctx.author.id != 899645707164729364:
                await ctx.send('権限がありません。')
                return
            return await fn(ctx, *args, **kwargs)
        return wrapper

    @staticmethod
    def admin_only(fn):
        @wraps(fn)
        async def wrapper(ctx: commands.Context, *args, **kwargs):
            if not ctx.author.guild_permissions.administrator:
                await ctx.send('権限がありません。')
                return
            return await fn(ctx, *args, **kwargs)
        return wrapper

    @staticmethod
    def ignore_bot(fn):
        @wraps(fn)
        async def wrapper(ctx: commands.Context, *args, **kwargs):
            if ctx.author.bot:
                return
            return await fn(ctx, *args, **kwargs)
        return wrapper


def get_current_history(user_id) -> str:
    current_chat = chat_config.get(user_id)
    if current_chat is None:
        return str(user_id)
    return f'{user_id}_{current_chat}'


def get_filename(user_id, name):
    if name is None:
        return get_current_history(user_id)
    elif name.lower() == '<main>':
        return str(user_id)
    else:
        return f'{user_id}_{name}'


def is_command(message: str) -> bool:
    """Check whether the message is a command.
    """
    commands = ['.' + c for c in bot.all_commands.keys()]
    for i in commands:
        if message.startswith(i):
            return True
    return False


def check_history_name(name: str | None) -> bool:
    """Check whether the history name is correct.
    """
    return name is not None and name.lower() != '<main>' and not chatname_compile.fullmatch(name)


async def attachment_to_inline_data(attachment: discord.Attachment):
    return {
        'mime_type': attachment.content_type,
        'data': await attachment.read()
    }


def textnsplit(text, n):
    l = []
    while len(text) > 0:
        l.append(text[:n])
        text = text[n:]
    return l


@bot.event
async def on_ready():
    print('起動\n----')
    game = discord.Game('.help')
    await bot.change_presence(activity=game)


@bot.listen()
async def on_message(message: discord.Message):
    if (
        message.author.bot or
        message.channel.id not in channel_config or
        is_command(message.content)
    ):
        return

    reset_after = message_cooldown(message.author.id)
    if reset_after is not None:
        await message.reply(f'Cooldown {reset_after}', delete_after=3.0)
        return

    inline_data_list = await asyncio.gather(*[
        asyncio.create_task(attachment_to_inline_data(a))
        for a in message.attachments
    ])
    text = message.content or None
    content = to_jsonable(build_content_data(text, inline_data_list))
    max_history_size = max_history_config.get(message.author.id)

    async with message.channel.typing():
        with history_handler(get_current_history(message.author.id)) as history:
            if max_history_size is None:
                use_history = history
            else:
                use_history = history[-max_history_size:]
            model = model_config.get(message.author.id)
            res, errors = await gemini.generate(use_history + [content], KEYS, model)
            if res is not None:
                finish_reason = res['candidates'][0]['finishReason']
                if finish_reason != 'STOP':
                    await message.reply(f'生成失敗 reason:{finish_reason}')
                    return
                res_content = res['candidates'][0]['content']
                res_text: str = res_content['parts'][0]['text']
                for seg in textnsplit(res_text, 2000):
                    await message.reply(seg, suppress=True)
                history.append(content)
                history.append(res_content)
            else:
                await message.reply(f'{str(errors)} {len(errors)}'[:500])

            channel = await bot.fetch_channel(1257930523901169736)
            await channel.send(f'{str(errors)} {len(errors)}'[:500])


@bot.command()
@restrict.ignore_bot
async def pop(ctx: commands.Context, index: int = -1):
    """会話履歴からメッセージを削除します。 (.pop <index>)
    """
    with history_handler(get_current_history(ctx.author.id)) as history:
        history.pop(index)
    await ctx.send('メッセージを消去しました。')


@bot.command()
@restrict.ignore_bot
async def clear(ctx: commands.Context):
    with history_handler(get_current_history(ctx.author.id)) as history:
        history.clear()
    await ctx.send('メッセージを全消去しました。')


@bot.command()
@restrict.ignore_bot
async def export(ctx: commands.Context, name: str | None = None):
    if check_history_name(name):
        await ctx.send('履歴が存在しません。')
        return
    filename = get_filename(ctx.author.id, name)
    try:
        with open(f'{HISTORY_FOLDER}/{filename}.json', 'rb') as file:
            await ctx.send(file=discord.File(file, f'{filename}.json'))
    except FileNotFoundError:
        await ctx.send('履歴が存在しません。')


@bot.command()
@restrict.ignore_bot
async def change(ctx: commands.Context, name: str | None = None):
    if check_history_name(name):
        await ctx.send('名前は英語と数字のみ')
        return
    if name is not None and name.lower() == '<main>':
        name = None
    chat_config[ctx.author.id] = name
    await ctx.send('変更しました')


@bot.command()
@restrict.ignore_bot
async def delete(ctx: commands.Context, name: str | None = None):
    if check_history_name(name):
        await ctx.send('削除できませんでした。')
        return

    filename = get_filename(ctx.author.id, name)
    try:
        os.remove(f'{HISTORY_FOLDER}/{filename}.json')
        message = '削除しました。'
    except:
        message = '削除できませんでした。'

    if name is None or chat_config.get(ctx.author.id) == name:
        chat_config[ctx.author.id] = None
    await ctx.send(message)


@bot.command(name='list')
@restrict.ignore_bot
async def list_(ctx: commands.Context):
    all_histories = os.listdir(HISTORY_FOLDER)
    user_id = str(ctx.author.id)
    owning = []
    for filename in all_histories:
        if not filename.startswith(user_id):
            continue
        parts = filename.removesuffix('.json').split('_')
        if len(parts) == 1:
            owning.append('<main>')
        else:
            owning.append(parts[1])
    await ctx.send('Histories:\n' + '\n'.join([f'- {i}' for i in owning]))


@bot.command()
@restrict.ignore_bot
async def current(ctx: commands.Context):
    await ctx.send(chat_config.get(ctx.author.id) or '<main>')


@bot.command()
@restrict.ignore_bot
@restrict.admin_only
async def on(ctx: commands.Context):
    channel_config.append(ctx.channel.id)
    await ctx.send('オンにしました。')


@bot.command()
@restrict.ignore_bot
@restrict.admin_only
async def off(ctx: commands.Context):
    channel_config.remove(ctx.channel.id)
    await ctx.send('オフにしました。')


@bot.command(name='import')
@restrict.ignore_bot
async def import_(ctx: commands.Context, name: str | None = None):
    if check_history_name(name):
        await ctx.send('会話名は英語と数字のみ')
        return
    if not ctx.message.attachments:
        await ctx.send('JSONファイルを添付してください。')
        return
    attachment = ctx.message.attachments[0]
    MAX_FILE_SIZE = 300 * 1000  # 300KB
    if attachment.size > MAX_FILE_SIZE:
        await ctx.send('ファイルサイズは300KB以下にしてください。')
        return
    if not attachment.content_type.startswith('application/json'):
        await ctx.send('不正なフォーマットです。')
        return

    bytes = await attachment.read()
    try:
        obj = json.loads(bytes.decode('utf-8'))
    except json.JSONDecodeError:
        await ctx.send('不正なJSONです。')
        return

    result, messages = check_history(obj)
    if not result:
        await ctx.send(' / '.join(messages[::-1]))
        return

    filename = get_filename(ctx.author.id, name)
    with open(f'{HISTORY_FOLDER}/{filename}.json', 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)

    await ctx.send('インポートに成功しました。')


@bot.command()
@restrict.ignore_bot
async def maxhistory(ctx: commands.Context, size: str | None = None):
    if size is not None and not size.isnumeric():
        await ctx.send('不正な値です。')
        return
    max_history_config[ctx.author.id] = size if size is None else int(size)
    await ctx.send(f'履歴の最大数を{size}に設定しました。')


@bot.command()
@restrict.ignore_bot
async def cp(ctx: commands.Context):
    with history_handler(get_current_history(ctx.author.id)) as history:
        change_position(history)
    await ctx.send('⇔')


@bot.command()
@restrict.ignore_bot
async def currentmodel(ctx: commands.Context):
    await ctx.send(model_config.get(ctx.author.id, DEFAULT_GEMINI_MODEL))


@bot.command()
@restrict.ignore_bot
async def model(ctx: commands.Context, name: str | None = None):
    model_config[ctx.author.id] = name
    await ctx.send(f'model={name}')


@bot.command()
@restrict.ignore_bot
async def help(ctx: commands.Context):
    await ctx.send(dedent("""
        このボットは、Geminiを使用してAIとチャットできるボットです。
        会話を複数管理し、切り替えることもできます。
        コマンド一覧は以下の通りです。

        **履歴管理コマンド:**
        - .pop <index> - 会話履歴からメッセージを削除します。
        - .clear - 会話履歴からメッセージを全消去します。
        - .export <name> - 会話履歴を出力します。
        - .import - JSON形式のhistoryをimportします。
        - .maxhistory <size> - 使用する履歴の最大数を設定します。

        **会話管理コマンド:**
        - .change <name> - 会話を切り替えます。
        - .delete <name> - 会話履歴を削除します。
        - .list - 会話一覧を取得します。
        - .current - 現在の会話を取得します。

        **管理コマンド:**
        - .on - チャンネルをオンに設定します（管理者のみ）。
        - .off - チャンネルをオフに設定します（管理者のみ）。
        """))


try:
    # Configure settings
    if not os.path.exists(CONFIG_FOLDER):
        os.makedirs(CONFIG_FOLDER)
    if not os.path.exists(HISTORY_FOLDER):
        os.makedirs(HISTORY_FOLDER)
    def save_configs():
        Config.save('room', chat_config)
        Config.save('channel', channel_config)
        Config.save('maxhistory', max_history_config)
        Config.save('model', model_config)
    def save_configs_task():
        while True:
            time.sleep(60)
            save_configs()
    threading.Thread(target=save_configs_task).start()

    chat_config: dict[int, str | None] = Config.load('room', {}, int_keys=True)  # dict <user_id:chatname>
    channel_config: list[int] = Config.load('channel', [])   # list of channel ids
    max_history_config: dict[int, int | None] = Config.load('maxhistory', {}, int_keys=True)
    model_config: dict[int, str | None] = Config.load('model', {}, int_keys=True)
    message_cooldown = Cooldown(5.0)

    # -----------
    DEBUG = False
    # -----------

    bot.run(TOKEN_DEV if DEBUG else TOKEN)
finally:
    save_configs()
