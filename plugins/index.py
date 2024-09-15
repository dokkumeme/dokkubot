import logging
import asyncio
import psutil  # Import for resource monitoring
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, MessageIdInvalid
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
import re
from pyrogram.errors import MessageIdInvalid

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
lock = asyncio.Lock()

async def handle_flood_wait():
    await asyncio.sleep(11)  # Default wait time; adjust if necessary

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing")
    _, raju, chat, lst_msg_id, from_user = query.data.split("#")
    if raju == 'reject':
        await query.message.delete()
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been declined by our moderators.',
                               reply_to_message_id=int(lst_msg_id))
        return

    if lock.locked():
        return await query.answer('Wait until previous process completes.', show_alert=True)
    
    msg = query.message

    await query.answer('Processing...⏳', show_alert=True)
    if int(from_user) not in ADMINS:
        await bot.send_message(int(from_user),
                               f'Your Submission for indexing {chat} has been accepted by our moderators and will be added soon.',
                               reply_to_message_id=int(lst_msg_id))
    
    await msg.edit(
        "Starting Indexing",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
        )
    )
    
    try:
        chat = int(chat)
    except:
        chat = chat
    await index_files_to_db(int(lst_msg_id), chat, msg, bot)


@Client.on_message((filters.forwarded | (filters.regex("(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text) & filters.private & filters.incoming)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile("(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int(("-100" + chat_id))
    elif message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return
    
    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply('This may be a private channel / group. Make me an admin over there to index the files.')
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid Link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Errors - {e}')
    
    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except FloodWait as e:
        logger.info(f"FloodWait: Sleeping for {e.value} seconds")
        await asyncio.sleep(e.value)  # Wait and retry
        return await send_for_index(bot, message)  # Retry after waiting
    except Exception as e:
        return await message.reply('Make sure that I am an admin in the channel, if it is private.')
    
    if k.empty:
        return await message.reply('This may be a group and I am not an admin of the group.')

    await index_files_to_db(last_msg_id, chat_id, message, bot)
    await message.reply('Indexing started.')


@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if ' ' in message.text:
        _, skip = message.text.split(" ")
        try:
            skip = int(skip)
        except:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"Successfully set SKIP number as {skip}")
        temp.CURRENT = int(skip)
    else:
        await message.reply("Give me a skip number")


async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    try:
        async with lock:
            current = temp.CURRENT
            temp.CANCEL = False
            async for message in bot.iter_messages(chat, lst_msg_id, temp.CURRENT):
                if temp.CANCEL:
                    await msg.edit(f"Successfully Cancelled!!\n\nSaved <code>{total_files}</code> files to dataBase!\n"
                                   f"Duplicate Files Skipped: <code>{duplicate}</code>\nDeleted Messages Skipped: <code>{deleted}</code>\n"
                                   f"Non-Media messages skipped: <code>{no_media + unsupported}</code>(Unsupported Media - `{unsupported}` )\n"
                                   f"Errors Occurred: <code>{errors}</code>")
                    break
                current += 1

                # Add logging for each file indexed
                logger.info(f"Indexing file #{current}: {message.id}")

                if current % 20 == 0:
                    # Log resource usage (memory)
                    mem_usage = psutil.virtual_memory().percent
                    logger.info(f"Memory usage: {mem_usage}%")

                    can = [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
                    reply = InlineKeyboardMarkup(can)
                    try:
                        await msg.edit_text(
                            text=f"Total messages fetched: <code>{current}</code>\n"
                                 f"Total messages saved: <code>{total_files}</code>\n"
                                 f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                                 f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                                 f"Non-Media messages skipped: <code>{no_media + unsupported}</code>"
                                 f"(Unsupported Media - `{unsupported}` )\n"
                                 f"Errors Occurred: <code>{errors}</code>\n"
                                 f"Memory usage: <code>{mem_usage}%</code>",
                            reply_markup=reply
                        )
                    except MessageIdInvalid:
                        logger.error("Message ID invalid or message too old to edit, sending a new message.")
                        await bot.send_message(msg.chat.id, f"Error: Couldn't edit the message, here's an update:\n"
                                                            f"Total messages fetched: <code>{current}</code>\n"
                                                            f"Total messages saved: <code>{total_files}</code>\n"
                                                            f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                                                            f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                                                            f"Non-Media messages skipped: <code>{no_media + unsupported}</code>"
                                                            f"(Unsupported Media - `{unsupported}` )\n"
                                                            f"Errors Occurred: <code>{errors}</code>\n"
                                                            f"Memory usage: <code>{mem_usage}%</code>")

                    # Send update to the log channel
                    await bot.send_message(LOG_CHANNEL, f"Indexing update:\n"
                                                        f"Total messages fetched: {current}\n"
                                                        f"Total messages saved: {total_files}\n"
                                                        f"Duplicate Files Skipped: {duplicate}\n"
                                                        f"Deleted Messages Skipped: {deleted}\n"
                                                        f"Non-Media messages skipped: {no_media + unsupported} (Unsupported Media - {unsupported})\n"
                                                        f"Errors Occurred: {errors}\n"
                                                        f"Memory usage: {mem_usage}%")

                    # Add delay after every 100 files to avoid overload
                    if current % 100 == 0:
                        logger.info("Processed 100 files, pausing for 5 seconds...")
                        await asyncio.sleep(5)

                if message.empty:
                    deleted += 1
                    continue
                elif not message.media:
                    no_media += 1
                    continue
                elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
                    unsupported += 1
                    continue
                media = getattr(message, message.media.value, None)
                if not media:
                    unsupported += 1
                    continue
                media.file_type = message.media.value
                media.caption = message.caption
                aynav, vnay = await save_file(media)
                if aynav:
                    total_files += 1
                elif vnay == 0:
                    duplicate += 1
                elif vnay == 2:
                    errors += 1
    except FloodWait as e:
        logger.info(f"FloodWait: Sleeping for {e.value} seconds")
        await asyncio.sleep(e.value)  # Correctly wait for the time specified in the error
        await index_files_to_db(lst_msg_id, chat, msg, bot)  # Retry after waiting
    except Exception as e:
        logger.exception(e)
        try:
            await msg.edit(f'Error: {e}')
        except MessageIdInvalid:
            logger.error("Failed to edit message: Message ID invalid")
    finally:
        try:
            await msg.edit(f'Successfully saved <code>{total_files}</code> to dataBase!\n'
                           f'Duplicate Files Skipped: <code>{duplicate}</code>\n'
                           f'Deleted Messages Skipped: <code>{deleted}</code>\n'
                           f'Non-Media messages skipped: <code>{no_media + unsupported}</code>'
                           f'(Unsupported Media - `{unsupported}` )\nErrors Occurred: <code>{errors}</code>\n'
                           f'Memory usage: <code>{mem_usage}%</code>')
            # Send final update to the log channel
            await bot.send_message(LOG_CHANNEL, f"Indexing completed:\n"
                                                f"Total messages fetched: {current}\n"
                                                f"Total messages saved: {total_files}\n"
                                                f"Duplicate Files Skipped: {duplicate}\n"
                                                f"Deleted Messages Skipped: {deleted}\n"
                                                f"Non-Media messages skipped: {no_media + unsupported} (Unsupported Media - {unsupported})\n"
                                                f"Errors Occurred: {errors}\n"
                                                f"Memory usage: {mem_usage}%")
        except MessageIdInvalid:
            logger.error("Failed to edit final message: Message ID invalid")
