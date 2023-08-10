import os
import time
import asyncio
from pathlib import Path
from typing import Dict, List, Union, Optional

import aiohttp
from git.repo import Repo
from git.exc import GitCommandError, NoSuchPathError, InvalidGitRepositoryError

from gsuid_core.logger import logger
from gsuid_core.utils.plugins_config.gs_config import core_plugins_config

from .api import CORE_PATH, PLUGINS_PATH, proxy_url, plugins_lib

plugins_list: Dict[str, Dict[str, str]] = {}

is_update_dep = core_plugins_config.get_config('AutoUpdateDep').data


# 传入一个path对象
async def run_poetry_install(path: Optional[Path] = None) -> int:
    if path is None:
        path = CORE_PATH
    # 检测path是否是一个目录
    if not path.is_dir():
        raise ValueError(f"{path} is not a directory")
    # 检测path下是否存在poetry.lock文件
    lock_file = path / "poetry.lock"
    if not lock_file.is_file():
        raise FileNotFoundError(f"{lock_file} does not exist")
    # 异步执行poetry install命令，并返回返回码
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf8"

    proc = await asyncio.create_subprocess_shell(
        'poetry install',
        cwd=path,
        stdout=asyncio.subprocess.PIPE,
        shell=True,
        env=env,
    )
    # stdout, stderr = await proc.communicate()

    output = ''
    if proc.stdout:
        while True:
            data = await proc.stdout.readline()
            if not data:
                break
            line = data.decode()
            await proc.wait()
            output += line

    logger.info(output)

    if 'No dependencies to install or update' in output:
        return 200
    else:
        return -1 if proc.returncode is None else proc.returncode


def check_retcode(retcode: int) -> str:
    if retcode == 200:
        return '无需更新依赖！'
    elif retcode == 0:
        return '新增/更新依赖成功!'
    else:
        return f'更新失败, 错误码{retcode}'


async def update_all_plugins() -> List[str]:
    log_list = []
    for plugin in PLUGINS_PATH.iterdir():
        if plugin.is_dir():
            log_list.extend(update_from_git(0, plugin))
    return log_list


async def refresh_list() -> List[str]:
    refresh_list = []
    async with aiohttp.ClientSession() as session:
        logger.info(f'稍等...开始刷新插件列表, 地址: {plugins_lib}')
        async with session.get(plugins_lib) as resp:
            _plugins_list: Dict[
                str, Dict[str, Dict[str, str]]
            ] = await resp.json()
            for i in _plugins_list['plugins']:
                if i.lower() not in plugins_list:
                    refresh_list.append(i)
                    logger.info(f'[刷新插件列表] 列表新增插件 {i}')
                plugins_list[i.lower()] = _plugins_list['plugins'][i]
    return refresh_list


async def get_plugins_list() -> Dict[str, Dict[str, str]]:
    if not plugins_list:
        await refresh_list()
    return plugins_list


async def get_plugins_url(name: str) -> Optional[Dict[str, str]]:
    if not plugins_list:
        await refresh_list()

    if name in plugins_list:
        return plugins_list[name]
    for _n in plugins_list:
        sim = len(set(_n) & set(name))
        if sim >= 0.5 * len(_n):
            return plugins_list[_n]
    else:
        return None


def install_plugins(plugins: Dict[str, str]) -> str:
    plugin_name = plugins['link'].split('/')[-1]
    git_path = f'{proxy_url}{plugins["link"]}.git'
    logger.info(f'稍等...开始安装插件, 地址: {git_path}')
    path = PLUGINS_PATH / plugin_name
    if path.exists():
        return '该插件已经安装过了!'
    config = {'single_branch': True, 'depth': 1}

    if plugins['branch'] != 'main':
        config['branch'] = plugins['branch']

    Repo.clone_from(git_path, path, **config)
    logger.info(f'插件{plugin_name}安装成功!')
    return f'插件{plugin_name}安装成功!发送[gs重启]以应用!'


async def install_plugin(plugin_name: str) -> int:
    url = await get_plugins_url(plugin_name)
    if url is None:
        return -1
    install_plugins(url)
    return 0


def check_plugins(plugin_name: str) -> Optional[Repo]:
    path = PLUGINS_PATH / plugin_name
    if not path.exists():
        return None
    try:
        repo = Repo(path)
    except InvalidGitRepositoryError:
        return None
    return repo


def check_can_update(repo: Repo) -> bool:
    try:
        remote = repo.remote()  # 获取远程仓库
        remote.fetch()  # 从远程获取最新版本
    except GitCommandError as e:
        logger.error(f'发生Git命令错误{e}!')
        return False
    local_commit = repo.commit()  # 获取本地最新提交
    remote_commit = remote.fetch()[0].commit  # 获取远程最新提交
    return local_commit.hexsha != remote_commit.hexsha


def check_status(plugin_name: str) -> int:
    repo = check_plugins(plugin_name)
    if repo is None:
        return 3
    return 1 if check_can_update(repo) else 4


def update_from_git(
    level: int = 0,
    repo_like: Union[str, Path, None] = None,
    log_key: List[str] = [],
    log_limit: int = 5,
) -> List[str]:
    try:
        if repo_like is None:
            repo = Repo(CORE_PATH)
            plugin_name = '早柚核心'
            if is_update_dep:
                asyncio.create_task(run_poetry_install(CORE_PATH))
        elif isinstance(repo_like, Path):
            repo = Repo(repo_like)
            plugin_name = repo_like.name
        else:
            repo = check_plugins(repo_like)
            plugin_name = repo_like
    except InvalidGitRepositoryError:
        logger.warning('[更新] 更新失败, 非有效Repo路径!')
        return ['更新失败, 该路径并不是一个有效的GitRepo路径, 请使用`git clone`安装插件...']
    except NoSuchPathError:
        logger.warning('[更新] 更新失败, 该路径不存在!')
        return ['更新失败, 路径/插件不存在!']

    if not repo:
        logger.warning('[更新] 更新失败, 该插件不存在!')
        return ['更新失败, 不存在该插件!']

    o = repo.remotes.origin

    if level >= 2:
        logger.warning(f'[更新][{plugin_name}] 正在执行 git clean --xdf')
        logger.warning('[更新] 你有 2 秒钟的时间中断该操作...')
        time.sleep(2)
        repo.git.clean('-xdf')
    # 还原上次更改
    if level >= 1:
        logger.warning(f'[更新][{plugin_name}] 正在执行 git reset --hard')
        repo.git.reset('--hard')

    try:
        pull_log = o.pull()
        logger.info(f'[更新][{plugin_name}] {pull_log}')
        logger.info(f'[更新][{repo.head.commit.hexsha[:7]}] 获取远程最新版本')
    except GitCommandError as e:
        logger.warning(f'[更新] 更新失败...{e}!')
        return ['更新失败, 请检查控制台...']

    commits = list(repo.iter_commits(max_count=40))
    log_list = [f'更新插件 {plugin_name} 中...']
    for commit in commits:
        if isinstance(commit.message, str):
            if log_key:
                for key in log_key:
                    if key in commit.message:
                        log_list.append(commit.message.replace('\n', ''))
                        if len(log_list) >= log_limit:
                            break
            else:
                log_list.append(commit.message.replace('\n', ''))
                if len(log_list) >= log_limit:
                    break
    return log_list


def update_plugins(
    plugin_name: str,
    level: int = 0,
    log_key: List[str] = [],
    log_limit: int = 10,
) -> Union[str, List]:
    for _n in PLUGINS_PATH.iterdir():
        _name = _n.name
        sim = len(set(_name.lower()) & set(plugin_name.lower()))
        if sim >= 0.5 * len(_name):
            plugin_name = _name
            break

    return update_from_git(level, plugin_name, log_key, log_limit)
