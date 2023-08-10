from pathlib import Path
from typing import Any, Dict, List, Union

from msgspec import json as msgjson

from gsuid_core.logger import logger
from gsuid_core.data_store import get_res_path

from .models import GSC, GsBoolConfig
from .config_default import CONIFG_DEFAULT


class StringConfig:
    def __new__(cls, *args, **kwargs):
        # 判断sv是否已经被初始化
        name = args[0] if args else kwargs.get('config_name')
        if name is None:
            raise ValueError('Config.name is None!')

        if name in all_config_list:
            return all_config_list[name]
        _config = super().__new__(cls)
        all_config_list[name] = _config
        return _config

    def __init__(
        self, config_name: str, CONFIG_PATH: Path, config_list: Dict[str, GSC]
    ) -> None:
        self.config_list = config_list

        if not CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'wb') as file:
                file.write(msgjson.encode(config_list))

        self.config_name = config_name
        self.CONFIG_PATH = CONFIG_PATH
        self.config: Dict[str, GSC] = {}
        self.update_config()

    def __len__(self):
        return len(self.config)

    def __iter__(self):
        return iter(self.config)

    def __getitem__(self, key) -> GSC:
        return self.config[key]

    def write_config(self):
        with open(self.CONFIG_PATH, 'wb') as file:
            file.write(msgjson.format(msgjson.encode(self.config), indent=4))

    def update_config(self):
        # 打开config.json
        with open(self.CONFIG_PATH, 'r', encoding='UTF-8') as f:
            self.config: Dict[str, GSC] = msgjson.decode(
                f.read(),
                type=Dict[str, GSC],
            )
        # 对没有的值，添加默认值
        for key in self.config_list:
            if key not in self.config:
                self.config[key] = self.config_list[key]

        delete_keys = [key for key in self.config if key not in self.config_list]
        for key in delete_keys:
            self.config.pop(key)

        # 重新写回
        self.write_config()

    def get_config(self, key: str) -> Any:
        if key in self.config:
            return self.config[key]
        elif key in self.config_list:
            logger.info(
                f'[配置][{self.config_name}] 配置项 {key} 不存在, 但是默认配置存在, 已更新...'
            )
            self.update_config()
            return self.config[key]
        else:
            logger.warning(
                f'[配置][{self.config_name}] 配置项 {key} 不存在也没有配置, 返回默认参数...'
            )
            return GsBoolConfig('缺省值', '获取错误的配置项', False)

    def set_config(
        self, key: str, value: Union[str, List, bool, Dict]
    ) -> bool:
        if key in self.config_list:
            temp = self.config[key].data
            if type(value) == type(temp):
                # 设置值
                self.config[key].data = value  # type: ignore
                # 重新写回
                self.write_config()
                return True
            else:
                logger.warning(
                    f'[配置][{self.config_name}] 配置项 {key} 写入类型不正确, 停止写入...'
                )
                return False
        else:
            return False


all_config_list: Dict[str, StringConfig] = {}

core_plugins_config = StringConfig(
    'Core', get_res_path() / 'core_config.json', CONIFG_DEFAULT
)
