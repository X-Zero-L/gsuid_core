'''
虚空数据库 API 请求模块。
'''
from __future__ import annotations

import json
from typing import Dict, Literal, Optional

from httpx import AsyncClient

from ..types import AnyDict
from ..utils import _HEADER
from .models import AKaShaRank, AKaShaCharData, AkashaAbyssData
from .api import AKASHA_CHAR_URL, AKASHA_RANK_URL, AKASHA_ABYSS_URL


async def get_akasha_abyss_info() -> AkashaAbyssData:
    '''请求虚空数据库 API 深渊出场数据

    Returns:
        AkashaAbyssData: 虚空数据库 API 深渊出场数据响应数据
    '''  # noqa: E501
    raw_data = await _akasha_request(AKASHA_ABYSS_URL)
    raw_data = raw_data.lstrip('var static_abyss_total =')
    return json.loads(raw_data)


async def get_akasha_all_char_info() -> Dict[str, AKaShaCharData]:
    raw_data = await _akasha_request(AKASHA_CHAR_URL)
    raw_data = (
        raw_data.replace('\\', '')
        .lstrip('var static_card_details =')
        .replace('"[', '[')
        .replace(']"', ']')
        .replace('"{', '{')
        .replace('}"', '}')
    )
    return json.loads(raw_data)


async def get_akasha_abyss_rank(is_info: bool = False) -> AKaShaRank:
    raw_data = await _akasha_request(AKASHA_RANK_URL)
    raw_data = raw_data.lstrip('var static_abyss_total =')
    data_list = raw_data.split(';')
    data1 = data_list[0].lstrip('var static_schedule_version_dict =')
    data2 = data_list[1].lstrip('var static_abyss_record_dict =')
    schedule_version_dict = json.loads(data1)
    abyss_record_dict = json.loads(data2)
    return schedule_version_dict if is_info else abyss_record_dict


async def _akasha_request(
    url: str,
    method: Literal['GET', 'POST'] = 'GET',
    header: AnyDict = _HEADER,
    params: Optional[AnyDict] = None,
    data: Optional[AnyDict] = None,
) -> str:
    async with AsyncClient(
        headers=header,
        verify=False,
        timeout=None,
    ) as client:
        req = await client.request(
            method=method, url=url, params=params, data=data
        )
        return req.text
