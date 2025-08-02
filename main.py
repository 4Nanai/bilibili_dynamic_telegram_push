import asyncio
import json
import os
import random
import time
import logging
import smtplib
import yaml
from typing import Dict

from bilibili_api import user

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
DYNAMIC_RECENT_THRESHOLD = 60 * 10  # 10 minutes threshold for recent dynamics
DYNAMIC_UIDS = []
# DYNAMIC_UIDS = [16801939]
BOT_TOKEN: str = ""
CHAT_ID: str = ""

class UserInfo:
    def __init__(self, uid: int):
        self.uid = uid
        self.latest_id_str = ""

    async def push_new_dynamic(self, major: str, url: str, pics: list):
        bot = Bot(token=BOT_TOKEN)
        keyboard = [[InlineKeyboardButton("点击查看动态", url=url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        media_group = []
        if pics:
            media_group.append(InputMediaPhoto(media=pics[0]["url"], parse_mode=ParseMode.MARKDOWN_V2))
            for pic in pics[1:]:
                media_group.append(InputMediaPhoto(media=pic["url"]))
            try:
                await bot.send_media_group(
                    chat_id=CHAT_ID,
                    media=media_group,
                )
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=major,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup
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
                text=major,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )

users: Dict[int, UserInfo] = {}

def extract_dynamic_content(latest, username: str, uid: int):
    desc = ""
    major = ""
    pics = []
    if latest["modules"]["module_dynamic"]["desc"] != None:
        desc = latest["modules"]["module_dynamic"]["desc"].get("text", "")
    if latest["modules"]["module_dynamic"]["major"] != None:
        type = latest["modules"]["module_dynamic"]["major"].get("type")
        if type == "MAJOR_TYPE_OPUS":
            major = latest["modules"]["module_dynamic"]["major"]["opus"]["summary"].get("text", "")
            pics = latest["modules"]["module_dynamic"]["major"]["opus"].get("pics", [])
        elif type == "MAJOR_TYPE_ARCHIVE":
            major = latest["modules"]["module_dynamic"]["major"]["archive"].get("title", "")
            pics = latest["modules"]["module_dynamic"]["major"]["archive"].get("cover", [])

    content = major or desc or "这是一条没有内容的动态"
    return content, pics

async def check_dynamics(uid: int):
    u = user.User(uid)
    offset = ""
    page = await u.get_dynamics_new(offset)
    latest = max(page["items"][:10], key=lambda d: d["modules"]["module_author"]["pub_ts"])
    id_str = latest["id_str"]
    pub_ts = latest["modules"]["module_author"]["pub_ts"]
    username = latest["modules"]["module_author"]["name"]
    global users
    user_info = users.get(uid)

    if user_info is None:
        return
    if time.time() - pub_ts > DYNAMIC_RECENT_THRESHOLD:
        return
    pub_action = latest["modules"]["module_author"]["pub_action"]
    if pub_action == "直播了":
        logger.info(f"[动态] {username}(uid: {uid}) 最新动态是直播动作，跳过检查")
        return
    pub_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pub_ts + 8 * 3600))
    logger.info(f"[动态] 检查 {username}(uid: {uid}) 的新动态，最新 ID: {id_str}, 发布时间: {pub_time}")
    if id_str != user_info.latest_id_str:
        user_info.latest_id_str = id_str
        url = f"https://t.bilibili.com/{id_str}"
        content, pics = extract_dynamic_content(latest, username, uid)

        message = f"[**{username}**](https://space.bilibili.com/{uid}) 发布了新动态: {content}\n时间: {pub_time}\n"
        logger.info(f"[动态] {username}(uid: {uid}) 有新动态: {message}")
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

async def main(config: str = "config.yaml"):
    global DYNAMIC_UIDS, BOT_TOKEN, CHAT_ID, DYNAMIC_INTERVAL, DYNAMIC_INTERVAL_VARIATION, DYNAMIC_RECENT_THRESHOLD
    if not os.path.isabs(config):
        cwd = os.getcwd()
        config = os.path.join(cwd, config)
    with open(config, "r") as file:
        c = yaml.safe_load(file)
    DYNAMIC_UIDS = c.get("dynamic_uids", [])
    BOT_TOKEN = c.get("bot_token", "")
    CHAT_ID = c.get("chat_id", "")
    DYNAMIC_INTERVAL = c.get("dynamic_interval", 60 * 5)
    DYNAMIC_INTERVAL_VARIATION = c.get("dynamic_interval_variation", 60)
    DYNAMIC_RECENT_THRESHOLD = c.get("dynamic_recent_threshold", 60 * 10)
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("配置文件缺少必要的字段，请检查 config.yaml")
        return
    await check_dynamics_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已手动终止")