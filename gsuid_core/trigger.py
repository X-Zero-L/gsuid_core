import re
from typing import Literal, Callable

from gsuid_core.models import Event


class Trigger:
    def __init__(
        self,
        type: Literal[
            'prefix',
            'suffix',
            'keyword',
            'fullmatch',
            'command',
            'file',
            'regex',
        ],
        keyword: str,
        func: Callable,
        block: bool = False,
        to_me: bool = False,
    ):
        self.type = type
        self.keyword = keyword
        self.func = func
        self.block = block
        self.to_me = to_me

    def check_command(self, ev: Event) -> bool:
        if self.to_me:
            if not ev.is_tome:
                return False
        if self.type == 'file':
            return self._check_file(self.keyword, ev)
        msg = ev.raw_text
        return getattr(self, f'_check_{self.type}')(self.keyword, msg)

    def _check_prefix(self, prefix: str, msg: str) -> bool:
        return bool(msg.startswith(prefix) and not self._check_fullmatch(prefix, msg))

    def _check_command(self, command: str, msg: str) -> bool:
        return bool(msg.startswith(command))

    def _check_suffix(self, suffix: str, msg: str) -> bool:
        return bool(msg.endswith(suffix) and not self._check_fullmatch(suffix, msg))

    def _check_keyword(self, keyword: str, msg: str) -> bool:
        return keyword in msg

    def _check_fullmatch(self, keyword: str, msg: str) -> bool:
        return msg == keyword

    def _check_file(self, file_type: str, ev: Event) -> bool:
        if ev.file_name and ev.file_name.split('.')[-1] == file_type:
            if ev.file:
                return True
        return False

    def _check_regex(self, pattern: str, msg: str) -> bool:
        return bool(command_list := re.findall(pattern, msg))

    async def get_command(self, msg: Event) -> Event:
        if self.type != 'regex':
            msg.command = self.keyword
            msg.text = msg.raw_text.replace(self.keyword, '')
        else:
            command_list = re.findall(self.keyword, msg.raw_text)
            msg.command = '|'.join(command_list)
            text_list = re.split(self.keyword, msg.raw_text)
            msg.text = '|'.join(text_list)
        return msg
