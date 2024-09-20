import asyncio
import random
import string
from datetime import datetime, timedelta, timezone
from dateutil import parser
from time import time
from urllib.parse import unquote, quote
import brotli

import aiohttp
import json
from json import dump as dp, loads as ld
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw import types
from .agents import generate_random_user_agent
from bot.config import settings

from bot.utils import logger
from bot.utils.logger import SelfTGClient
from bot.exceptions import InvalidSession
from .headers import headers
from .helper import format_duration

self_tg_client = SelfTGClient()

class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0
        self.username = None
        self.first_name = None
        self.last_name = None
        self.fullname = None
        self.start_param = None
        self.peer = None
        self.first_run = None

        self.session_ug_dict = self.load_user_agents() or []

        headers['User-Agent'] = self.check_user_agent()

    async def generate_random_user_agent(self):
        return generate_random_user_agent(device_type='android', browser_type='chrome')

    def info(self, message):
        from bot.utils import info
        info(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def debug(self, message):
        from bot.utils import debug
        debug(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def warning(self, message):
        from bot.utils import warning
        warning(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def error(self, message):
        from bot.utils import error
        error(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def critical(self, message):
        from bot.utils import critical
        critical(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def success(self, message):
        from bot.utils import success
        success(f"<light-yellow>{self.session_name}</light-yellow> | {message}")

    def save_user_agent(self):
        user_agents_file_name = "user_agents.json"

        if not any(session['session_name'] == self.session_name for session in self.session_ug_dict):
            user_agent_str = generate_random_user_agent()

            self.session_ug_dict.append({
                'session_name': self.session_name,
                'user_agent': user_agent_str})

            with open(user_agents_file_name, 'w') as user_agents:
                json.dump(self.session_ug_dict, user_agents, indent=4)

            logger.success(f"<light-yellow>{self.session_name}</light-yellow> | User agent saved successfully")

            return user_agent_str

    def load_user_agents(self):
        user_agents_file_name = "user_agents.json"

        try:
            with open(user_agents_file_name, 'r') as user_agents:
                session_data = json.load(user_agents)
                if isinstance(session_data, list):
                    return session_data

        except FileNotFoundError:
            logger.warning("User agents file not found, creating...")

        except json.JSONDecodeError:
            logger.warning("User agents file is empty or corrupted.")

        return []

    def check_user_agent(self):
        load = next(
            (session['user_agent'] for session in self.session_ug_dict if session['session_name'] == self.session_name),
            None)

        if load is None:
            return self.save_user_agent()

        return load

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            with_tg = True

            if not self.tg_client.is_connected:
                with_tg = False
                try:
                    await self.tg_client.connect()
                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            if settings.USE_REF == True:
                ref_id = settings.REF_ID
            else:
                ref_id = 'coub__marker_18361539'

            self.start_param = random.choices([ref_id, "coub__marker_18361539"], weights=[75, 25], k=1)[0]
            peer = await self.tg_client.resolve_peer('coub')
            InputBotApp = types.InputBotAppShortName(bot_id=peer, short_name="coub")

            web_view = await self_tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotApp,
                platform='android',
                write_allowed=True,
                start_param=self.start_param
            ), self)

            headers['Referer'] = f"https://www.binance.com/en/game/tg/moon-bix?tgWebAppStartParam={self.start_param}"

            auth_url = web_view.url

            tg_web_data = unquote(
                string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0])

            try:
                if self.user_id == 0:
                    information = await self.tg_client.get_me()
                    self.user_id = information.id
                    self.first_name = information.first_name or ''
                    self.last_name = information.last_name or ''
                    self.username = information.username or ''
            except Exception as e:
                print(e)

            if with_tg is False:
                await self.tg_client.disconnect()

            return tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(
                f"<light-yellow>{self.session_name}</light-yellow> | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def login(self, http_client: aiohttp.ClientSession, tg_data):
        try:
            json_data = {
                 "query": tg_data,
                 "socialType": "telegram",
            },

            resp = await http_client.post(
                "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/third-party/access/accessToken",
                json=json_data,
                ssl=False
            )

            if resp.status == 520:
                self.warning('Relogin')
                await asyncio.sleep(delay=5)

            resp_json = await resp.json()

            if resp_json['data'] != None and resp_json['success'] == True:
                data = resp_json['data']
                return data.get("accessToken"), data.get("refreshToken")
            else:
                return None, None

        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Login error {error}")
            return None, None

    async def get_user_info(self, http_client: aiohttp.ClientSession):
        try:
            json_data = {"resourceId":2056}
            resp = await http_client.get(
                 f"https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/user/user-info",
                 json=json_data
                 ssl=False
            )
            json = await resp.json()
            return json.get('data')
        except Exception as e:
            self.error(f"Error occurred during getting user info: {e}")
            return None

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin')
            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"<light-yellow>{self.session_name}</light-yellow> | Proxy: {proxy} | 😢 Error: {error}")

    async def solve_task(self, http_client: aiohttp.ClientSession, task: dict):
        ignore_task = []
        task_id = task.get("id")
        task_title = task.get("title")
        task_status = task.get("status")
        start_task_url = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/task/list/{task_id}"
        claim_task_url = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/task/list/{task_id}"
        if task_id in ignore_task:
            return
        if task_status == "job done":
            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Already claim task id: <magenta>{task_id}</magenta>")
            return
        if task_status == "READY_FOR_CLAIM":
            resp = await http_client.post(
                claim_task_url,
                ssl=False
            )
            json = await resp.json()
            status = resp.get("status")
            if status == "FINISHED":
                logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Success complete task id: <magenta>{task_id}</magenta>")
                return

        resp = await http_client.post(start_task_url, ssl=False)
        await asyncio.sleep(5)
        status = resp.get("status")
        if status == "STARTED":
            resp = await http_client.post(
                claim_task_url,
                ssl=False
            )
            json = await resp.json()
            status = resp.get("status")
            if status == "FINISHED":
                logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Success complete task id: <magenta>{task_id}</magenta>")
                return

    def solve_tasks(self, http_client: aiohttp.ClientSession):
        url_tasks = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/task/list"

        json_data = { "resourceId":2056 }
        resp = await http_client.get(url_tasks, json=json_data, ssl=False)

        json = await resp.json()

        if json.get('status') == False:
            return None

        data = json.get('data').get('data')

        for section in data:
            task_list = section['taskList']

    async def auto_farming(self, http_client: aiohttp.ClientSession):
        url = "https://bin.bnbstatic.com/api/i18n/-/web/cms/en/growth-game-ui"

        while True:
            resp = await http_client.post(url, headers, "")
            json = resp.json()
            end = json.get("endTime")

            if end is None:
                await asyncio.sleep(3)
                continue
            break

        end_date = datetime.fromtimestamp(end / 1000)

        logger.success(f"<light-yellow>{self.session_name}</light-yellow> | Start farming successfully!")
        logger.info(f"<light-yellow>{self.session_name}</light-yellow> | End farming : {white}{end_date}")

        return round(end / 1000)

    async def play_game(self, http_client: aiohttp.ClientSession):
        url_play = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/play"
        url_claim = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/claim"
        url_balance = "https://www.binance.com/bapi/growth/v1/friendly/growth-paas/mini-app-activity/third-party/balance"

        while True:
            res = self.http(url_balance, headers)
            play = res.dp().get("playPasses")
            if play is None:
                self.log(f"{yellow}failed get game ticket !")
                break
            self.log(f"{green}you have {white}{play}{green} game ticket")
            if play <= 0:
                return
            for i in range(play):
                if self.is_expired(access_token):
                    return True
                res = self.http(url_play, headers, "")
                game_id = res.dp().get("gameId")
                if game_id is None:
                    message = res.dp().get("message", "")
                    if message == "cannot start game":
                        self.log(
                            f"{yellow}{message},will be tried again in the next round."
                        )
                        return False
                    self.log(f"{yellow}{message}")
                    continue
                while True:
                    self.countdown(30)
                    point = random.randint(self.MIN_WIN, self.MAX_WIN)
                    data = dp.dumps({"gameId": game_id, "points": point})
                    res = self.http(url_claim, headers, data)
                    if "OK" in res.text:
                        self.log(
                            f"{green}success earn {white}{point}{green} from game !"
                        )
                        self.get_balance(access_token, only_show_balance=True)
                        break

                    message = res.dp().get("message", "")
                    if message == "game session not finished":
                        continue

                    self.log(f"{red}failed earn {white}{point}{red} from game !")
                    break


    async def run(self, proxy: str | None) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Bot will start in <ly>{random_delay}s</ly>")
            await asyncio.sleep(random_delay)

        access_token = None
        refresh_token = None
        login_need = True

        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        http_client = CloudflareScraper(headers=headers, connector=proxy_conn)

        if proxy:
            await self.check_proxy(http_client=http_client, proxy=proxy)

        while True:
            try:
                if login_need:
                    if "x-growth-token" in http_client.headers:
                        del http_client.headers["x-growth-token"]

                    tg_data = await self.get_tg_web_data(proxy=proxy)

                    access_token, refresh_token = await self.login(http_client=http_client, tg_data=tg_data)

                    http_client.headers["x-growth-token"] = f"{access_token}"

                    if self.first_run is not True:
                        self.success("Logged in successfully")
                        self.first_run = True

                    login_need = False

                await asyncio.sleep(delay=3)

            except Exception as error:
                logger.error(
                    f"<light-yellow>{self.session_name}</light-yellow> | 😢 Unknown error during login: {error}")
                await asyncio.sleep(delay=3)

            try:
                user_info = await self.get_user_info(http_client=http_client)

                await asyncio.sleep(delay=2)

                if user_info is not None:
                    meta_info = user_info.get('metaInfo')
                    total_grade = meta_info['totalGrade']
                    referral_total_grade = meta_info['referralTotalGrade']
                    total_balance = total_grade + referral_total_grade
                    current_attempts = meta_info['totalAttempts'] - meta_info['totalAttempts']
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Points: 💰<light-green>{'{:,}'.format(total_balance)}</light-green> 💰")
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Your Attempts: 🚀<light-green>{'{:,}'.format(current_attempts)}</light-green> 🚀")

                logger.info(f"<light-yellow>{self.session_name}</light-yellow> | 💤 sleep 600 seconds 💤")
                await asyncio.sleep(delay=600)

            except Exception as error:
                logger.error(
                    f"<light-yellow>{self.session_name}</light-yellow> | 😢 Unknown error: {error}")

async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | 😢 Invalid Session 😢")
