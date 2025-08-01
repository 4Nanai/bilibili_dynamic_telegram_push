import asyncio
import json
import os
import random
import time
import logging
import smtplib
from typing import Dict

from bilibili_api import user, live
from bilibili_api import sync

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

logger = logging.getLogger("Bilibili_Dynamic_Push")
logger.setLevel(logging.INFO)
stream_handler: logging.StreamHandler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
logger.addHandler(stream_handler)

DYNAMIC_INTERVAL = 60 * 5  # 5 minutes
DYNAMIC_INTERVAL_VARIATION = 60  # ±1 minute variation
DYNAMIC_UIDS = [1217754423, 1660392980, 1878154667, 1900141897, 1203217682, 434334701]  # Replace with
# DYNAMIC_UIDS = [16801939]
BOT_TOKEN: str = ""
CHAT_ID: str = ""

class UserInfo:
    def __init__(self, uid: int):
        self.uid = uid
        self.latest_id_str = ""

    async def push_new_dynamic(self, content: str, url: str, pics: list):
        bot = Bot(token=BOT_TOKEN)
        keyboard = [[InlineKeyboardButton("点击查看动态", url=url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        media_group = []
        if pics:
            media_group.append(InputMediaPhoto(media=pics[0]["url"], caption=content, parse_mode=ParseMode.MARKDOWN_V2))
            for pic in pics[1:]:
                media_group.append(InputMediaPhoto(media=pic["url"]))
            try:
                await bot.send_media_group(
                    chat_id=CHAT_ID,
                    media=media_group,
                )
            except TimedOut:
                await asyncio.sleep(5)
                await bot.send_media_group(
                    chat_id=CHAT_ID,
                    media=media_group,
                )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=content,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )

users: Dict[int, UserInfo] = {}

async def check_dynamics(uid: int):
    u = user.User(uid)
    offset = ""
    page = await u.get_dynamics_new(offset)
    latest = max(page["items"][:10], key=lambda d: d["modules"]["module_author"]["pub_ts"])
    id_str = latest["id_str"]
    pub_ts = latest["modules"]["module_author"]["pub_ts"]
    global users
    user_info = users.get(uid)

    if user_info is None:
        return

    if id_str != user_info.latest_id_str:
        user_info.latest_id_str = id_str
        url = f"https://t.bilibili.com/{id_str}"
        username = latest["modules"]["module_author"]["name"]
        content= ""
        try:
            content = latest["modules"]["module_dynamic"]["major"]["opus"]["summary"]["text"]
        except KeyError:
            content = "这是一条没有文字说明的动态"
            
        pics = []
        try:
            pics = latest["modules"]["module_dynamic"]["major"]["opus"]["pics"]
        except KeyError:
            pics = []
        
        message = f"[B站新动态通知] 用户: {username}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pub_ts))}\n内容: {content}"
        escaped_message = escape_markdown(message, version=2)
        asyncio.create_task(user_info.push_new_dynamic(escaped_message, url, pics))
    else:
        logger.info(f"[动态] UID {uid} 无新动态")

async def check_dynamics_loop():
    global users
    while True:
        interval = DYNAMIC_INTERVAL + random.randint(-DYNAMIC_INTERVAL_VARIATION, DYNAMIC_INTERVAL_VARIATION)
        logger.info("[动态监控] 开始新一轮检查")
        for uid in DYNAMIC_UIDS:
            if uid not in users:
                users[uid] = UserInfo(uid)
            await check_dynamics(uid)
            await asyncio.sleep(3)
        logger.info(f"[动态监控] 本轮检查结束，休眠 {interval} 秒")
        await asyncio.sleep(interval)

async def main():
    await check_dynamics_loop()

if __name__ == "__main__":
    try:
        sync(main())
    except KeyboardInterrupt:
        logger.info("程序已手动终止")