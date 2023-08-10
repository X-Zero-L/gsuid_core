'''
米游社 API 请求模块。
'''
from __future__ import annotations

import copy
import time
import uuid
import random
from abc import abstractmethod
from string import digits, ascii_letters
from typing import Any, Dict, List, Tuple, Union, Literal, Optional, cast

from aiohttp import TCPConnector, ClientSession, ContentTypeError

from gsuid_core.logger import logger
from gsuid_core.utils.database.api import DBSqla
from gsuid_core.utils.plugins_config.gs_config import core_plugins_config

from .api import _API
from .tools import (
    random_hex,
    random_text,
    get_ds_token,
    generate_os_ds,
    gen_payment_sign,
    get_web_ds_token,
    generate_passport_ds,
)
from .models import (
    BsIndex,
    GcgInfo,
    MysGame,
    MysSign,
    RegTime,
    GachaLog,
    MysGoods,
    MysOrder,
    SignInfo,
    SignList,
    AbyssData,
    IndexData,
    AuthKeyInfo,
    GcgDeckInfo,
    MonthlyAward,
    QrCodeStatus,
    CalculateInfo,
    DailyNoteData,
    GameTokenInfo,
    MysOrderCheck,
    RolesCalendar,
    CharDetailData,
    CookieTokenInfo,
    LoginTicketInfo,
)

proxy_url = core_plugins_config.get_config('proxy').data
ssl_verify = core_plugins_config.get_config('MhySSLVerify').data
RECOGNIZE_SERVER = {
    '1': 'cn_gf01',
    '2': 'cn_gf01',
    '5': 'cn_qd01',
    '6': 'os_usa',
    '7': 'os_euro',
    '8': 'os_asia',
    '9': 'os_cht',
}


class BaseMysApi:
    proxy_url: Optional[str] = proxy_url if proxy_url else None
    mysVersion = '2.44.1'
    _HEADER = {
        'x-rpc-app_version': mysVersion,
        'User-Agent': (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) '
            f'AppleWebKit/605.1.15 (KHTML, like Gecko) miHoYoBBS/{mysVersion}'
        ),
        'x-rpc-client_type': '5',
        'Referer': 'https://webstatic.mihoyo.com/',
        'Origin': 'https://webstatic.mihoyo.com',
    }
    _HEADER_OS = {
        'x-rpc-app_version': '1.5.0',
        'x-rpc-client_type': '4',
        'x-rpc-language': 'zh-cn',
    }
    MAPI = _API
    is_sr = False
    RECOGNIZE_SERVER = RECOGNIZE_SERVER
    chs = {}
    dbsqla: DBSqla = DBSqla()

    @abstractmethod
    async def _upass(self, header: Dict) -> str:
        ...

    @abstractmethod
    async def _pass(
        self, gt: str, ch: str, header: Dict
    ) -> Tuple[Optional[str], Optional[str]]:
        ...

    @abstractmethod
    async def get_ck(
        self, uid: str, mode: Literal['OWNER', 'RANDOM'] = 'RANDOM'
    ) -> Optional[str]:
        ...

    @abstractmethod
    async def get_stoken(self, uid: str) -> Optional[str]:
        ...

    @abstractmethod
    async def get_user_fp(self, uid: str) -> Optional[str]:
        ...

    @abstractmethod
    async def get_user_device_id(self, uid: str) -> Optional[str]:
        ...

    def get_device_id(self) -> str:
        return str(uuid.uuid4()).upper()

    def generate_seed(self, length: int):
        characters = '0123456789abcdef'
        return ''.join(random.choices(characters, k=length))

    async def generate_fp_by_uid(self, uid: str) -> str:
        seed_id = self.generate_seed(16)
        seed_time = str(int(time.time() * 1000))
        ext_fields = f'{{"userAgent":"{self._HEADER["User-Agent"]}",\
"browserScreenSize":281520,"maxTouchPoints":5,\
"isTouchSupported":true,"browserLanguage":"zh-CN","browserPlat":"iPhone",\
"browserTimeZone":"Asia/Shanghai","webGlRender":"Apple GPU",\
"webGlVendor":"Apple Inc.",\
"numOfPlugins":0,"listOfPlugins":"unknown","screenRatio":3,"deviceMemory":"unknown",\
"hardwareConcurrency":"4","cpuClass":"unknown","ifNotTrack":"unknown","ifAdBlock":0,\
"hasLiedResolution":1,"hasLiedOs":0,"hasLiedBrowser":0}}'
        body = {
            'seed_id': seed_id,
            'device_id': await self.get_user_device_id(uid),
            'platform': '5',
            'seed_time': seed_time,
            'ext_fields': ext_fields,
            'app_name': 'account_cn',
            'device_fp': '38d7ee834d1e9',
        }
        HEADER = copy.deepcopy(self._HEADER)
        res = await self._mys_request(
            url=self.MAPI['GET_FP_URL'],
            method='POST',
            header=HEADER,
            data=body,
        )
        if not isinstance(res, Dict):
            logger.error(f"获取fp连接失败{res}")
            return random_hex(13).lower()
        elif res["data"]["code"] != 200:
            logger.error(f"获取fp参数不正确{res['data']['msg']}")
            return random_hex(13).lower()
        else:
            return res["data"]["device_fp"]

    async def simple_mys_req(
        self,
        URL: str,
        uid: Union[str, bool],
        params: Dict = {},
        header: Dict = {},
        cookie: Optional[str] = None,
    ) -> Union[Dict, int]:
        if isinstance(uid, bool):
            is_os = uid
            server_id = (
                ('cn_qd01' if is_os else 'cn_gf01')
                if not self.is_sr
                else ('prod_gf_cn' if is_os else 'prod_gf_cn')
            )
        else:
            server_id = self.RECOGNIZE_SERVER.get(uid[0])
            is_os = int(uid[0]) >= 6
        ex_params = '&'.join([f'{k}={v}' for k, v in params.items()])
        if is_os:
            _URL = self.MAPI[f'{URL}_OS']
            HEADER = copy.deepcopy(self._HEADER_OS)
            HEADER['DS'] = generate_os_ds()
        else:
            _URL = self.MAPI[URL]
            HEADER = copy.deepcopy(self._HEADER)
            HEADER['DS'] = get_ds_token(
                ex_params if ex_params else f'role_id={uid}&server={server_id}'
            )
        HEADER.update(header)
        if cookie is not None:
            HEADER['Cookie'] = cookie
        elif 'Cookie' not in HEADER and isinstance(uid, str):
            ck = await self.get_ck(uid)
            if ck is None:
                return -51
            HEADER['Cookie'] = ck
        return await self._mys_request(
            url=_URL,
            method='GET',
            header=HEADER,
            params=params if params else {'server': server_id, 'role_id': uid},
            use_proxy=bool(is_os),
        )

    async def _mys_req_get(
        self,
        url: str,
        is_os: bool,
        params: Dict,
        header: Optional[Dict] = None,
    ) -> Union[Dict, int]:
        if is_os:
            _URL = self.MAPI[f'{url}_OS']
            HEADER = copy.deepcopy(self._HEADER_OS)
            use_proxy = True
        else:
            _URL = self.MAPI[url]
            HEADER = copy.deepcopy(self._HEADER)
            use_proxy = False
        if header:
            HEADER.update(header)

        if 'Cookie' not in HEADER and 'uid' in params:
            ck = await self.get_ck(params['uid'])
            if ck is None:
                return -51
            HEADER['Cookie'] = ck
        return await self._mys_request(
            url=_URL,
            method='GET',
            header=HEADER,
            params=params,
            use_proxy=use_proxy,
        )

    async def _mys_request(
        self,
        url: str,
        method: Literal['GET', 'POST'] = 'GET',
        header: Dict[str, Any] = _HEADER,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        use_proxy: Optional[bool] = False,
    ) -> Union[Dict, int]:
        async with ClientSession(
            connector=TCPConnector(verify_ssl=ssl_verify)
        ) as client:
            raw_data = {}
            uid = None
            if params and 'role_id' in params:
                uid = params['role_id']
                header['x-rpc-device_id'] = await self.get_user_device_id(uid)
                header['x-rpc-device_fp'] = await self.get_user_fp(uid)

            for _ in range(3):
                if 'Cookie' in header and header['Cookie'] in self.chs:
                    # header['x-rpc-challenge']=self.chs.pop(header['Cookie'])
                    if self.is_sr:
                        header['x-rpc-challenge'] = self.chs.pop(
                            header['Cookie']
                        )
                        if isinstance(params, Dict):
                            header['DS'] = get_ds_token(
                                '&'.join(
                                    [f'{k}={v}' for k, v in params.items()]
                                )
                            )

                    header['x-rpc-challenge_game'] = '6' if self.is_sr else '2'
                    header['x-rpc-page'] = (
                        '3.1.3_#/rpg' if self.is_sr else '3.1.3_#/ys'
                    )

                    if (
                        'x-rpc-challenge' in header
                        and not header['x-rpc-challenge']
                    ):
                        del header['x-rpc-challenge']
                        del header['x-rpc-page']
                        del header['x-rpc-challenge_game']

                print(header)
                async with client.request(
                    method,
                    url=url,
                    headers=header,
                    params=params,
                    json=data,
                    proxy=self.proxy_url if use_proxy else None,
                    timeout=300,
                ) as resp:
                    try:
                        raw_data = await resp.json()
                    except ContentTypeError:
                        _raw_data = await resp.text()
                        raw_data = {'retcode': -999, 'data': _raw_data}
                    logger.debug(raw_data)

                    # 判断retcode
                    if 'retcode' in raw_data:
                        retcode: int = raw_data['retcode']
                    elif 'code' in raw_data:
                        retcode: int = raw_data['code']
                    else:
                        retcode = 0

                    # 针对1034做特殊处理
                    if retcode == 1034:
                        if uid and self.is_sr and _ == 0:
                            sqla = self.dbsqla.get_sqla('TEMP')
                            new_fp = await self.generate_fp_by_uid(uid)
                            await sqla.update_user_data(uid, {'fp': new_fp})
                            header['x-rpc-device_fp'] = new_fp
                            if isinstance(params, Dict):
                                header['DS'] = get_ds_token(
                                    '&'.join(
                                        [f'{k}={v}' for k, v in params.items()]
                                    )
                                )
                        else:
                            ch = await self._upass(header)
                            self.chs[header['Cookie']] = ch
                    elif retcode == -10001 and uid:
                        sqla = self.dbsqla.get_sqla('TEMP')
                        new_fp = await self.generate_fp_by_uid(uid)
                        await sqla.update_user_data(uid, {'fp': new_fp})
                        header['x-rpc-device_fp'] = new_fp
                    elif retcode != 0:
                        return retcode
                    else:
                        return raw_data
            else:
                return -999

    '''
    async def _mys_request(
        self,
        url: str,
        method: Literal['GET', 'POST'] = 'GET',
        header: Dict[str, Any] = _HEADER,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        use_proxy: Optional[bool] = False,
    ) -> Union[Dict, int]:
        import types
        import inspect

        async with ClientSession(
            connector=TCPConnector(verify_ssl=ssl_verify)
        ) as client:
            if 'Cookie' in header:
                if header['Cookie'] in self.chs:
                    header['x-rpc-challenge'] = self.chs.pop(header["Cookie"])

            async with client.request(
                method,
                url=url,
                headers=header,
                params=params,
                json=data,
                proxy=self.proxy_url if use_proxy else None,
                timeout=300,
            ) as resp:
                try:
                    raw_data = await resp.json()
                except ContentTypeError:
                    _raw_data = await resp.text()
                    raw_data = {'retcode': -999, 'data': _raw_data}
                logger.debug(raw_data)

                # 判断retcode
                if 'retcode' in raw_data:
                    retcode: int = raw_data['retcode']
                elif 'code' in raw_data:
                    retcode: int = raw_data['code']
                else:
                    retcode = 0

                # 针对1034做特殊处理
                if retcode == 1034:
                    try:
                        # 获取ch
                        ch = await self._upass(header)
                        # 记录ck -> ch的对照表
                        if "Cookie" in header:
                            self.chs[header["Cookie"]] = ch
                        # 获取当前的栈帧
                        curframe = inspect.currentframe()
                        # 确保栈帧存在
                        assert curframe
                        # 获取调用者的栈帧
                        calframe = curframe.f_back
                        # 确保调用者的栈帧存在
                        assert calframe
                        # 获取调用者的函数名
                        caller_name = calframe.f_code.co_name
                        # 获取调用者函数的局部变量字典
                        caller_args = inspect.getargvalues(calframe).locals
                        # 获取调用者的参数列表
                        caller_args2 = inspect.getargvalues(calframe).args
                        # # 生成一个字典，键为调用者的参数名，值为对应的局部变量值，如果不存在则为None
                        caller_args3 = {
                            k: caller_args.get(k, None) for k in caller_args2
                        }
                        if caller_name != '_mys_req_get':
                            return await types.FunctionType(
                                calframe.f_code, globals()
                            )(**caller_args3)
                        else:
                            curframe = calframe
                            calframe = curframe.f_back
                            assert calframe
                            caller_name = calframe.f_code.co_name
                            caller_args = inspect.getargvalues(calframe).locals
                            caller_args2 = inspect.getargvalues(calframe).args
                            caller_args3 = {
                                k: caller_args.get(k, None)
                                for k in caller_args2
                            }
                            return await types.FunctionType(
                                calframe.f_code, globals()
                            )(**caller_args3)
                    except Exception as e:
                        logger.error(e)
                        traceback.print_exc()
                        return -999
                elif retcode != 0:
                    return retcode
                return raw_data
    '''


class MysApi(BaseMysApi):
    async def _pass(
        self, gt: str, ch: str, header: Dict
    ) -> Tuple[Optional[str], Optional[str]]:
        if _pass_api := core_plugins_config.get_config('_pass_API').data:
            data = await self._mys_request(
                url=f'{_pass_api}&gt={gt}&challenge={ch}',
                method='GET',
                header=header,
            )
            if isinstance(data, int):
                return None, None
            validate = data['data']['validate']
            ch = data['data']['challenge']
        else:
            validate = None

        return validate, ch

    async def _upass(self, header: Dict, is_bbs: bool = False) -> str:
        logger.info('[upass] 进入处理...')
        if is_bbs:
            raw_data = await self.get_bbs_upass_link(header)
        else:
            raw_data = await self.get_upass_link(header)
        if isinstance(raw_data, int):
            return ''
        gt = raw_data['data']['gt']
        ch = raw_data['data']['challenge']

        vl, ch = await self._pass(gt, ch, header)

        if vl:
            await self.get_header_and_vl(header, ch, vl)
            if ch:
                logger.info(f'[upass] 获取ch -> {ch}')
                return ch
            else:
                return ''
        else:
            return ''

    async def get_upass_link(self, header: Dict) -> Union[int, Dict]:
        header['DS'] = get_ds_token('is_high=false')
        return await self._mys_request(
            url=self.MAPI['VERIFICATION_URL'],
            method='GET',
            header=header,
        )

    async def get_bbs_upass_link(self, header: Dict) -> Union[int, Dict]:
        header['DS'] = get_ds_token('is_high=false')
        return await self._mys_request(
            url=self.MAPI['BBS_VERIFICATION_URL'],
            method='GET',
            header=header,
        )

    async def get_header_and_vl(self, header: Dict, ch, vl):
        header['DS'] = get_ds_token(
            '',
            {
                'geetest_challenge': ch,
                'geetest_validate': vl,
                'geetest_seccode': f'{vl}|jordan',
            },
        )
        _ = await self._mys_request(
            url=self.MAPI['VERIFY_URL'],
            method='POST',
            header=header,
            data={
                'geetest_challenge': ch,
                'geetest_validate': vl,
                'geetest_seccode': f'{vl}|jordan',
            },
        )

    def check_os(self, uid: str) -> bool:
        return int(uid[0]) >= 6

    async def get_info(self, uid, ck: Optional[str]) -> Union[IndexData, int]:
        data = await self.simple_mys_req('PLAYER_INFO_URL', uid, cookie=ck)
        if isinstance(data, Dict):
            data = cast(IndexData, data['data'])
        return data

    async def get_daily_data(self, uid: str) -> Union[DailyNoteData, int]:
        data = await self.simple_mys_req('DAILY_NOTE_URL', uid)
        if isinstance(data, Dict):
            data = cast(DailyNoteData, data['data'])
        return data

    async def get_gcg_info(self, uid: str) -> Union[GcgInfo, int]:
        data = await self.simple_mys_req('GCG_INFO', uid)
        if isinstance(data, Dict):
            data = cast(GcgInfo, data['data'])
        return data

    async def get_gcg_deck(self, uid: str) -> Union[GcgDeckInfo, int]:
        data = await self.simple_mys_req('GCG_DECK_URL', uid)
        if isinstance(data, Dict):
            data = cast(GcgDeckInfo, data['data'])
        return data

    async def get_cookie_token(
        self, token: str, uid: str
    ) -> Union[CookieTokenInfo, int]:
        data = await self._mys_request(
            self.MAPI['GET_COOKIE_TOKEN_BY_GAME_TOKEN'],
            'GET',
            params={
                'game_token': token,
                'account_id': uid,
            },
        )
        if isinstance(data, Dict):
            data = cast(CookieTokenInfo, data['data'])
        return data

    async def get_sign_list(self, uid) -> Union[SignList, int]:
        is_os = self.check_os(uid)
        if is_os:
            params = {
                'act_id': 'e202102251931481',
                'lang': 'zh-cn',
            }
        else:
            params = {'act_id': 'e202009291139501'}
        data = await self._mys_req_get('SIGN_LIST_URL', is_os, params)
        if isinstance(data, Dict):
            data = cast(SignList, data['data'])
        return data

    async def get_sign_info(self, uid) -> Union[SignInfo, int]:
        server_id = self.RECOGNIZE_SERVER.get(str(uid)[0])
        is_os = self.check_os(uid)
        if is_os:
            params = {
                'act_id': 'e202102251931481',
                'lang': 'zh-cn',
                'region': server_id,
                'uid': uid,
            }
            header = {
                'DS': generate_os_ds(),
            }
        else:
            params = {
                'act_id': 'e202009291139501',
                'region': server_id,
                'uid': uid,
            }
            header = {}
        data = await self._mys_req_get('SIGN_INFO_URL', is_os, params, header)
        if isinstance(data, Dict):
            data = cast(SignInfo, data['data'])
        return data

    async def mys_sign(
        self, uid, header={}, server_id='cn_gf01'
    ) -> Union[MysSign, int]:
        server_id = self.RECOGNIZE_SERVER.get(str(uid)[0])
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        if int(str(uid)[0]) < 6:
            HEADER = copy.deepcopy(self._HEADER)
            HEADER['Cookie'] = ck
            HEADER['x-rpc-device_id'] = random_hex(32)
            HEADER['x-rpc-app_version'] = '2.44.1'
            HEADER['x-rpc-client_type'] = '5'
            HEADER['X_Requested_With'] = 'com.mihoyo.hyperion'
            HEADER['DS'] = get_web_ds_token(True)
            HEADER['Referer'] = (
                'https://webstatic.mihoyo.com/bbs/event/signin-ys/index.html'
                '?bbs_auth_required=true&act_id=e202009291139501'
                '&utm_source=bbs&utm_medium=mys&utm_campaign=icon'
            )
            HEADER.update(header)
            data = await self._mys_request(
                url=self.MAPI['SIGN_URL'],
                method='POST',
                header=HEADER,
                data={
                    'act_id': 'e202009291139501',
                    'uid': uid,
                    'region': server_id,
                },
            )
        else:
            HEADER = copy.deepcopy(self._HEADER_OS)
            HEADER['Cookie'] = ck
            HEADER['DS'] = generate_os_ds()
            HEADER.update(header)
            data = await self._mys_request(
                url=self.MAPI['SIGN_URL_OS'],
                method='POST',
                header=HEADER,
                data={
                    'act_id': 'e202102251931481',
                    'lang': 'zh-cn',
                    'uid': uid,
                    'region': server_id,
                },
                use_proxy=True,
            )
        if isinstance(data, Dict):
            data = cast(MysSign, data['data'])
        return data

    async def get_award(self, uid) -> Union[MonthlyAward, int]:
        server_id = self.RECOGNIZE_SERVER.get(str(uid)[0])
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        if int(str(uid)[0]) < 6:
            HEADER = copy.deepcopy(self._HEADER)
            HEADER['Cookie'] = ck
            HEADER['DS'] = get_web_ds_token(True)
            HEADER['x-rpc-device_id'] = random_hex(32)
            data = await self._mys_request(
                url=self.MAPI['MONTHLY_AWARD_URL'],
                method='GET',
                header=HEADER,
                params={
                    'act_id': 'e202009291139501',
                    'bind_region': server_id,
                    'bind_uid': uid,
                    'month': '0',
                    'bbs_presentation_style': 'fullscreen',
                    'bbs_auth_required': 'true',
                    'utm_source': 'bbs',
                    'utm_medium': 'mys',
                    'utm_campaign': 'icon',
                },
            )
        else:
            HEADER = copy.deepcopy(self._HEADER_OS)
            HEADER['Cookie'] = ck
            HEADER['x-rpc-device_id'] = random_hex(32)
            HEADER['DS'] = generate_os_ds()
            data = await self._mys_request(
                url=self.MAPI['MONTHLY_AWARD_URL_OS'],
                method='GET',
                header=HEADER,
                params={
                    'act_id': 'e202009291139501',
                    'region': server_id,
                    'uid': uid,
                    'month': '0',
                },
                use_proxy=True,
            )
        if isinstance(data, Dict):
            data = cast(MonthlyAward, data['data'])
        return data

    async def get_draw_calendar(self, uid: str) -> Union[int, RolesCalendar]:
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        hk4e_token = await self.get_hk4e_token(uid)
        header = {'Cookie': f'{ck};{hk4e_token}'}
        params = {
            'lang': 'zh-cn',
            'badge_uid': uid,
            'badge_region': server_id,
            'game_biz': 'hk4e_cn',
            'activity_id': 20220301153521,
            'year': 2023,
        }
        data = await self._mys_request(
            self.MAPI['CALENDAR_URL'], 'GET', header, params
        )
        return cast(RolesCalendar, data['data']) if isinstance(data, Dict) else data

    async def get_bs_index(self, uid: str) -> Union[int, BsIndex]:
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        hk4e_token = await self.get_hk4e_token(uid)
        header = {'Cookie': f'{ck};{hk4e_token}'}
        data = await self._mys_request(
            self.MAPI['BS_INDEX_URL'],
            'GET',
            header,
            {
                'lang': 'zh-cn',
                'badge_uid': uid,
                'badge_region': server_id,
                'game_biz': 'hk4e_cn',
                'activity_id': 20220301153521,
            },
        )
        return cast(BsIndex, data['data']) if isinstance(data, Dict) else data

    async def post_draw(self, uid: str, role_id: int) -> Union[int, Dict]:
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        hk4e_token = await self.get_hk4e_token(uid)
        header = {'Cookie': f'{ck};{hk4e_token}'}
        data = await self._mys_request(
            self.MAPI['RECEIVE_URL'],
            'POST',
            header,
            {
                'lang': 'zh-cn',
                'badge_uid': uid,
                'badge_region': server_id,
                'game_biz': 'hk4e_cn',
                'activity_id': 20220301153521,
            },
            {'role_id': role_id},
        )
        if isinstance(data, Dict):
            return data
        elif data == -512009:
            return {'data': None, 'message': '这张画片已经被收录啦~', 'retcode': -512009}
        else:
            return -999

    async def get_spiral_abyss_info(
        self, uid: str, schedule_type='1', ck: Optional[str] = None
    ) -> Union[AbyssData, int]:
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        data = await self.simple_mys_req(
            'PLAYER_ABYSS_INFO_URL',
            uid,
            {
                'role_id': uid,
                'schedule_type': schedule_type,
                'server': server_id,
            },
            cookie=ck,
        )
        if isinstance(data, Dict):
            data = cast(AbyssData, data['data'])
        return data

    async def get_character(
        self, uid, character_ids, ck
    ) -> Union[CharDetailData, int]:
        server_id = self.RECOGNIZE_SERVER.get(str(uid)[0])
        if int(str(uid)[0]) < 6:
            HEADER = copy.deepcopy(self._HEADER)
            HEADER['Cookie'] = ck
            HEADER['DS'] = get_ds_token(
                '',
                {
                    'character_ids': character_ids,
                    'role_id': uid,
                    'server': server_id,
                },
            )
            data = await self._mys_request(
                self.MAPI['PLAYER_DETAIL_INFO_URL'],
                'POST',
                HEADER,
                data={
                    'character_ids': character_ids,
                    'role_id': uid,
                    'server': server_id,
                },
            )
        else:
            HEADER = copy.deepcopy(self._HEADER_OS)
            HEADER['Cookie'] = ck
            HEADER['DS'] = generate_os_ds()
            data = await self._mys_request(
                self.MAPI['PLAYER_DETAIL_INFO_URL_OS'],
                'POST',
                HEADER,
                data={
                    'character_ids': character_ids,
                    'role_id': uid,
                    'server': server_id,
                },
                use_proxy=True,
            )
        if isinstance(data, Dict):
            data = cast(CharDetailData, data['data'])
        return data

    async def get_calculate_info(
        self, uid, char_id: int
    ) -> Union[CalculateInfo, int]:
        server_id = self.RECOGNIZE_SERVER.get(str(uid)[0])
        data = await self.simple_mys_req(
            'CALCULATE_INFO_URL',
            uid,
            {'avatar_id': char_id, 'uid': uid, 'region': server_id},
        )
        if isinstance(data, Dict):
            data = cast(CalculateInfo, data['data'])
        return data

    async def get_mihoyo_bbs_info(
        self,
        mys_id: str,
        cookie: Optional[str] = None,
        is_os: bool = False,
    ) -> Union[List[MysGame], int]:
        if not cookie:
            cookie = await self.get_ck(mys_id, 'OWNER')
        data = await self.simple_mys_req(
            'MIHOYO_BBS_PLAYER_INFO_URL',
            is_os,
            {'uid': mys_id},
            {'Cookie': cookie},
        )
        if isinstance(data, Dict):
            data = cast(List[MysGame], data['data']['list'])
        return data

    async def create_qrcode_url(self) -> Union[Dict, int]:
        device_id: str = ''.join(random.choices(ascii_letters + digits, k=64))
        app_id: str = '8'
        data = await self._mys_request(
            self.MAPI['CREATE_QRCODE'],
            'POST',
            header={},
            data={'app_id': app_id, 'device': device_id},
        )
        if isinstance(data, Dict):
            url: str = data['data']['url']
            ticket = url.split('ticket=')[1]
            return {
                'app_id': app_id,
                'ticket': ticket,
                'device': device_id,
                'url': url,
            }
        return data

    async def check_qrcode(
        self, app_id: str, ticket: str, device: str
    ) -> Union[QrCodeStatus, int]:
        data = await self._mys_request(
            self.MAPI['CHECK_QRCODE'],
            'POST',
            data={
                'app_id': app_id,
                'ticket': ticket,
                'device': device,
            },
        )
        if isinstance(data, Dict):
            data = cast(QrCodeStatus, data['data'])
        return data

    async def get_gacha_log_by_authkey(
        self,
        uid: str,
        gacha_type: str = '301',
        page: int = 1,
        end_id: str = '0',
    ) -> Union[int, GachaLog]:
        server_id = 'cn_qd01' if uid[0] == '5' else 'cn_gf01'
        authkey_rawdata = await self.get_authkey_by_cookie(uid)
        if isinstance(authkey_rawdata, int):
            return authkey_rawdata
        authkey = authkey_rawdata['authkey']
        data = await self._mys_request(
            url=self.MAPI['GET_GACHA_LOG_URL'],
            method='GET',
            header=self._HEADER,
            params={
                'authkey_ver': '1',
                'sign_type': '2',
                'auth_appid': 'webview_gacha',
                'init_type': '200',
                'gacha_id': 'fecafa7b6560db5f3182222395d88aaa6aaac1bc',
                'timestamp': str(int(time.time())),
                'lang': 'zh-cn',
                'device_type': 'mobile',
                'plat_type': 'ios',
                'region': server_id,
                'authkey': authkey,
                'game_biz': 'hk4e_cn',
                'gacha_type': gacha_type,
                'page': page,
                'size': '20',
                'end_id': end_id,
            },
        )
        if isinstance(data, Dict):
            data = cast(GachaLog, data['data'])
        return data

    async def get_cookie_token_by_game_token(
        self, token: str, uid: str
    ) -> Union[CookieTokenInfo, int]:
        data = await self._mys_request(
            self.MAPI['GET_COOKIE_TOKEN_BY_GAME_TOKEN'],
            'GET',
            params={
                'game_token': token,
                'account_id': uid,
            },
        )
        if isinstance(data, Dict):
            data = cast(CookieTokenInfo, data['data'])
        return data

    async def get_cookie_token_by_stoken(
        self, stoken: str, mys_id: str, full_sk: Optional[str] = None
    ) -> Union[CookieTokenInfo, int]:
        HEADER = copy.deepcopy(self._HEADER)
        HEADER['Cookie'] = full_sk if full_sk else f'stuid={mys_id};stoken={stoken}'
        data = await self._mys_request(
            url=self.MAPI['GET_COOKIE_TOKEN_URL'],
            method='GET',
            header=HEADER,
            params={
                'stoken': stoken,
                'uid': mys_id,
            },
        )
        if isinstance(data, Dict):
            data = cast(CookieTokenInfo, data['data'])
        return data

    async def get_stoken_by_login_ticket(
        self, lt: str, mys_id: str
    ) -> Union[LoginTicketInfo, int]:
        data = await self._mys_request(
            url=self.MAPI['GET_STOKEN_URL'],
            method='GET',
            header=self._HEADER,
            params={
                'login_ticket': lt,
                'token_types': '3',
                'uid': mys_id,
            },
        )
        if isinstance(data, Dict):
            data = cast(LoginTicketInfo, data['data'])
        return data

    async def get_stoken_by_game_token(
        self, account_id: int, game_token: str
    ) -> Union[GameTokenInfo, int]:
        _data = {
            'account_id': account_id,
            'game_token': game_token,
        }
        data = await self._mys_request(
            self.MAPI['GET_STOKEN'],
            'POST',
            {
                'x-rpc-app_version': '2.41.0',
                'DS': generate_passport_ds(b=_data),
                'x-rpc-aigis': '',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'x-rpc-game_biz': 'bbs_cn',
                'x-rpc-sys_version': '11',
                'x-rpc-device_id': uuid.uuid4().hex,
                'x-rpc-device_fp': ''.join(
                    random.choices(ascii_letters + digits, k=13)
                ),
                'x-rpc-device_name': 'GenshinUid_login_device_lulu',
                'x-rpc-device_model': 'GenshinUid_login_device_lulu',
                'x-rpc-app_id': 'bll8iq97cem8',
                'x-rpc-client_type': '2',
                'User-Agent': 'okhttp/4.8.0',
            },
            data=_data,
        )
        if isinstance(data, Dict):
            data = cast(GameTokenInfo, data['data'])
        return data

    async def get_authkey_by_cookie(self, uid: str) -> Union[AuthKeyInfo, int]:
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        HEADER = copy.deepcopy(self._HEADER)
        stoken = await self.get_stoken(uid)
        if stoken is None:
            return -51
        HEADER['Cookie'] = stoken
        HEADER['DS'] = get_web_ds_token(True)
        HEADER['User-Agent'] = 'okhttp/4.8.0'
        HEADER['x-rpc-app_version'] = '2.44.1'
        HEADER['x-rpc-sys_version'] = '12'
        HEADER['x-rpc-client_type'] = '5'
        HEADER['x-rpc-channel'] = 'mihoyo'
        HEADER['x-rpc-device_id'] = random_hex(32)
        HEADER['x-rpc-device_name'] = random_text(random.randint(1, 10))
        HEADER['x-rpc-device_model'] = 'Mi 10'
        HEADER['Referer'] = 'https://app.mihoyo.com'
        HEADER['Host'] = 'api-takumi.mihoyo.com'
        data = await self._mys_request(
            url=self.MAPI['GET_AUTHKEY_URL'],
            method='POST',
            header=HEADER,
            data={
                'auth_appid': 'webview_gacha',
                'game_biz': 'hk4e_cn',
                'game_uid': uid,
                'region': server_id,
            },
        )
        if isinstance(data, Dict):
            data = cast(AuthKeyInfo, data['data'])
        return data

    async def get_hk4e_token(self, uid: str):
        # 获取e_hk4e_token
        server_id = self.RECOGNIZE_SERVER.get(uid[0])
        header = {
            'Cookie': await self.get_ck(uid, 'OWNER'),
            'Content-Type': 'application/json;charset=UTF-8',
            'Referer': 'https://webstatic.mihoyo.com/',
            'Origin': 'https://webstatic.mihoyo.com',
        }
        use_proxy = False
        data = {
            'game_biz': 'hk4e_cn',
            'lang': 'zh-cn',
            'uid': f'{uid}',
            'region': f'{server_id}',
        }
        if int(uid[0]) < 6:
            url = self.MAPI['HK4E_LOGIN_URL']
        else:
            url = self.MAPI['HK4E_LOGIN_URL_OS']
            data['game_biz'] = 'hk4e_global'
            use_proxy = True

        async with ClientSession() as client:
            async with client.request(
                        method='POST',
                        url=url,
                        headers=header,
                        json=data,
                        proxy=self.proxy_url if use_proxy else None,
                        timeout=300,
                    ) as resp:
                raw_data = await resp.json()
                if 'retcode' not in raw_data or raw_data['retcode'] != 0:
                    return None
                _k = resp.cookies['e_hk4e_token'].key
                _v = resp.cookies['e_hk4e_token'].value
                return f'{_k}={_v}'

    async def get_regtime_data(self, uid: str) -> Union[RegTime, int]:
        hk4e_token = await self.get_hk4e_token(uid)
        ck_token = await self.get_ck(uid, 'OWNER')
        params = {
            'game_biz': 'hk4e_cn',
            'lang': 'zh-cn',
            'badge_uid': uid,
            'badge_region': self.RECOGNIZE_SERVER.get(uid[0]),
        }
        data = await self.simple_mys_req(
            'REG_TIME',
            uid,
            params,
            {'Cookie': f'{hk4e_token};{ck_token}' if int(uid[0]) <= 5 else {}},
        )
        return cast(RegTime, data['data']) if isinstance(data, Dict) else data

    '''充值相关'''

    async def get_fetchgoods(self) -> Union[int, List[MysGoods]]:
        data = {
            'released_flag': True,
            'game': 'hk4e_cn',
            'region': 'cn_gf01',
            'uid': '1',
            'account': '1',
        }
        resp = await self._mys_request(
            url=self.MAPI['fetchGoodsurl'],
            method='POST',
            data=data,
        )
        if isinstance(resp, int):
            return resp
        return cast(List[MysGoods], resp['data']['goods_list'])

    async def topup(
        self,
        uid: str,
        goods: MysGoods,
        method: Literal['weixin', 'alipay'] = 'alipay',
    ) -> Union[int, MysOrder]:
        device_id = str(uuid.uuid4())
        HEADER = copy.deepcopy(self._HEADER)
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        HEADER['Cookie'] = ck
        account = HEADER['Cookie'].split('account_id=')[1].split(';')[0]
        order = {
            'account': str(account),
            'region': 'cn_gf01',
            'uid': uid,
            'delivery_url': '',
            'device': device_id,
            'channel_id': 1,
            'client_ip': '',
            'client_type': 4,
            'game': 'hk4e_cn',
            'amount': goods['price'],
            # 'amount': 600,
            'goods_num': 1,
            'goods_id': goods['goods_id'],
            'goods_title': f'{goods["goods_name"]}×{str(goods["goods_unit"])}'
            if int(goods['goods_unit']) > 0
            else goods['goods_name'],
            'price_tier': goods['tier_id'],
            # 'price_tier': 'Tier_1',
            'currency': 'CNY',
            'pay_plat': method,
        }
        data = {
            'order': order,
            'special_info': 'topup_center',
            'sign': gen_payment_sign(order),
        }
        HEADER['x-rpc-device_id'] = device_id
        HEADER['x-rpc-client_type'] = '4'
        resp = await self._mys_request(
            url=self.MAPI['CreateOrderurl'],
            method='POST',
            header=HEADER,
            data=data,
        )
        return resp if isinstance(resp, int) else cast(MysOrder, resp['data'])

    async def check_order(
        self, order: MysOrder, uid: str
    ) -> Union[int, MysOrderCheck]:
        HEADER = copy.deepcopy(self._HEADER)
        ck = await self.get_ck(uid, 'OWNER')
        if ck is None:
            return -51
        HEADER['Cookie'] = ck
        data = {
            'order_no': order['order_no'],
            'game': 'hk4e_cn',
            'region': 'cn_gf01',
            'uid': uid,
        }
        resp = await self._mys_request(
            url=self.MAPI['CheckOrderurl'],
            method='GET',
            header=HEADER,
            params=data,
        )
        return resp if isinstance(resp, int) else cast(MysOrderCheck, resp['data'])
