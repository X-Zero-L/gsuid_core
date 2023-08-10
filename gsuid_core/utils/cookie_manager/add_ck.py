from pathlib import Path
from typing import Dict, List
from http.cookies import SimpleCookie

from gsuid_core.utils.api.mys_api import mys_api
from gsuid_core.utils.database.api import DBSqla
from gsuid_core.utils.error_reply import UID_HINT

pic_path = Path(__file__).parent / 'pic'
id_list = [
    'login_uid',
    'login_uid_v2',
    'account_mid_v2',
    'account_mid',
    'account_id',
    'stuid',
    'ltuid',
    'ltmid',
    'stmid',
    'stmid_v2',
    'ltmid_v2',
    'stuid_v2',
    'ltuid_v2',
]
sk_list = ['stoken', 'stoken_v2']
ck_list = ['cookie_token', 'cookie_token_v2']
lt_list = ['login_ticket', 'login_ticket_v2']

get_sqla = DBSqla().get_sqla


async def get_ck_by_all_stoken(bot_id: str):
    sqla = get_sqla(bot_id)
    uid_list: List = await sqla.get_all_uid_list()
    uid_dict = {}
    for uid in uid_list:
        user_data = await sqla.select_user_data(uid)
        if user_data:
            uid_dict[uid] = user_data.user_id
    return await refresh_ck_by_uid_list(bot_id, uid_dict)


async def get_ck_by_stoken(bot_id: str, user_id: str):
    sqla = get_sqla(bot_id)
    uid_list: List = await sqla.get_bind_uid_list(user_id)
    uid_dict = {uid: user_id for uid in uid_list}
    return await refresh_ck_by_uid_list(bot_id, uid_dict)


async def refresh_ck_by_uid_list(bot_id: str, uid_dict: Dict):
    sqla = get_sqla(bot_id)
    uid_num = len(uid_dict)
    if uid_num == 0:
        return '请先绑定一个UID噢~'
    error_list = {}
    skip_num = 0
    error_num = 0
    for uid in uid_dict:
        stoken = await sqla.get_user_stoken(uid)
        if stoken is None:
            skip_num += 1
            error_num += 1
            continue
        else:
            qid = uid_dict[uid]
            try:
                mes = await _deal_ck(bot_id, stoken, qid)
            except TypeError:
                error_list[uid] = 'SK或CK已过期！'
                error_num += 1
                continue
            ok_num = mes.count('成功')
            if ok_num < 2:
                error_list[uid] = '可能是SK已过期~'
                error_num += 1
                continue

    s_im = f'执行完成~成功刷新CK{uid_num - error_num}个！跳过{skip_num}个!'
    f_im = '\n'.join([f'UID{u}:{error_list[u]}' for u in error_list])
    return f'{s_im}\n{f_im}' if f_im else s_im


async def deal_ck(bot_id: str, mes: str, user_id: str, mode: str = 'PIC'):
    im = await _deal_ck(bot_id, mes, user_id)
    if mode == 'PIC':
        im = await _deal_ck_to_pic(im)
    return im


async def _deal_ck_to_pic(im: str) -> bytes:
    ok_num = im.count('成功')
    if ok_num < 1:
        status_pic = pic_path / 'ck_no.png'
    elif ok_num < 2:
        status_pic = pic_path / 'ck_ok.png'
    else:
        status_pic = pic_path / 'all_ok.png'
    with open(status_pic, 'rb') as f:
        img = f.read()
    return img


async def get_account_id(simp_dict: SimpleCookie) -> str:
    return next((simp_dict[_id].value for _id in id_list if _id in simp_dict), '')


async def _deal_ck(bot_id: str, mes: str, user_id: str) -> str:
    sqla = get_sqla(bot_id)
    simp_dict = SimpleCookie(mes)
    uid = await sqla.get_bind_uid(user_id)
    sr_uid = await sqla.get_bind_sruid(user_id)
    uid_bind = sr_uid_bind = None

    if uid is None and sr_uid is None:
        return UID_HINT
    im_list = []
    is_add_stoken = False
    status = True
    app_cookie, stoken = '', ''
    account_id, cookie_token = '', ''
    if status:
        for sk in sk_list:
            if sk in simp_dict:
                account_id = await get_account_id(simp_dict)
                if not account_id:
                    return '该CK字段出错, 缺少login_uid或stuid或ltuid字段!'
                stoken = simp_dict[sk].value
                if stoken.startswith('v2_'):
                    if 'mid' not in simp_dict:
                        return 'v2类型SK必须携带mid...'
                    mid = simp_dict['mid'].value
                    app_cookie = (
                        f'stuid={account_id};stoken={stoken};mid={mid}'
                    )
                else:
                    app_cookie = f'stuid={account_id};stoken={stoken}'
                cookie_token_data = await mys_api.get_cookie_token_by_stoken(
                    stoken, account_id, app_cookie
                )
                if not isinstance(cookie_token_data, Dict):
                    return '返回值错误...'
                cookie_token = cookie_token_data['cookie_token']
                is_add_stoken = True
                status = False
                break
    if status:
        for lt in lt_list:
            if lt in simp_dict:
                # 寻找stoken
                login_ticket = simp_dict[lt].value
                account_id = await get_account_id(simp_dict)
                if not account_id:
                    return '该CK字段出错, 缺少login_uid或stuid或ltuid字段!'
                stoken_data = await mys_api.get_stoken_by_login_ticket(
                    login_ticket, account_id
                )
                if isinstance(stoken_data, Dict):
                    stoken = stoken_data['list'][0]['token']
                    app_cookie = f'stuid={account_id};stoken={stoken}'
                    cookie_token_data = (
                        await mys_api.get_cookie_token_by_stoken(
                            stoken, account_id
                        )
                    )
                    if isinstance(cookie_token_data, Dict):
                        cookie_token = cookie_token_data['cookie_token']
                        is_add_stoken = True
                        status = False
                        break
    if status:
        for ck in ck_list:
            if ck in simp_dict:
                # 寻找uid
                account_id = await get_account_id(simp_dict)
                if not account_id:
                    return '该CK字段出错, 缺少login_uid或stuid或ltuid字段!'
                cookie_token = simp_dict[ck].value
                status = False
                break
    if status:
        return (
            '添加Cookies失败!Cookies中应该包含cookie_token或者login_ticket相关信息!'
            '\n可以尝试退出米游社登陆重新登陆获取!'
        )

    account_cookie = f'account_id={account_id};cookie_token={cookie_token}'

    try:
        if sr_uid or (uid and int(uid[0]) < 6):
            mys_data = await mys_api.get_mihoyo_bbs_info(
                account_id, account_cookie
            )
        else:
            mys_data = await mys_api.get_mihoyo_bbs_info(
                account_id, account_cookie, True
            )
        # 剔除除了原神之外的其他游戏
        if isinstance(mys_data, List):
            for i in mys_data:
                if i['game_id'] == 2:
                    uid_bind = i['game_role_id']
                elif i['game_id'] == 6:
                    sr_uid_bind = i['game_role_id']
                if uid_bind and sr_uid_bind:
                    break
            else:
                if not uid_bind and not sr_uid_bind:
                    return f'你的米游社账号{account_id}尚未绑定原神/星铁账号,请前往米游社操作！'
    except Exception:
        pass

    if uid_bind:
        await sqla.refresh_cache(uid_bind)
    if sr_uid_bind:
        await sqla.refresh_cache(sr_uid_bind)

    if is_add_stoken:
        im_list.append(f'添加Stoken成功,stuid={account_id},stoken={stoken}')

    if uid is None:
        uid = '0'

    device_id = mys_api.get_device_id()
    fp = await mys_api.generate_fp_by_uid(uid)
    await sqla.insert_user_data(
        user_id,
        uid_bind,
        sr_uid_bind,
        account_cookie,
        app_cookie,
        fp,
        device_id,
    )

    im_list.extend(
        (
            f'添加Cookies成功,account_id={account_id},cookie_token={cookie_token}',
            'Cookies和Stoken属于个人重要信息,如果你是在不知情的情况下添加,请马上修改米游社账户密码,保护个人隐私！',
            '如果需要【gs开启自动签到】和【gs开启推送】还需要在【群聊中】使用命令“绑定uid”绑定你的uid。'
            '\n例如：绑定uid123456789。',
            '你可以使用命令【绑定信息】检查你的账号绑定情况！',
        )
    )
    return '\n'.join(im_list)
