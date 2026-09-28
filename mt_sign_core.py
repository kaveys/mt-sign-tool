# -*- coding: utf-8 -*-
"""
MT论坛 (bbs.binmt.cc) 签到脚本 —— 核心模块
====================================================
包含：HttpSession（纯标准库HTTP会话）、BinMTSigner（登录+签到逻辑）、
      ConfigManager（GUI版配置存储）、常量与SSL兼容处理。

依赖：仅 Python 标准库。
GUI版（可打包exe）和青龙面板命令行版本都从这里 import BinMTSigner 复用。
"""

import os
import re
import json
import time
import gzip
import random
import logging
import ssl
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
from datetime import datetime

# ============== 基础配置 ==============
BASE_URL = 'https://bbs.binmt.cc'
SIGN_PAGE = f'{BASE_URL}/k_misign-sign.html'
SIGN_API = f'{BASE_URL}/plugin.php?id=k_misign:sign&operation=qiandao'
LOGIN_INIT = (f'{BASE_URL}/member.php?mod=logging&action=login&infloat=yes'
              f'&handlekey=login&inajax=1&ajaxtarget=fwin_content_login')

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Safari/537.36')

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_CONFIG_DIR, 'mt_config.json')
LOG_FILE = os.path.join(_CONFIG_DIR, 'mt_sign.log')

# ============== SSL 上下文（兼容部分环境证书问题） ==============
try:
    _create_unverified_https = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https = None

# ============== 日志配置（给 GUI / CLI 外部使用；模块内默认 logger 已配文件句柄） ==============
logger = logging.getLogger('MTSign')
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    try:
        _fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                            '%Y-%m-%d %H:%M:%S'))
        logger.addHandler(_fh)
    except Exception:
        pass


# ============== 配置管理（仅 GUI 版使用；青龙命令行版不走这里） ==============
class ConfigManager:
    @staticmethod
    def load():
        default = {
            'accounts': [],
            'auto_start': False,
            'min_delay': 60,
            'max_delay': 300,
            'random_sign_time': False,
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                default.update(cfg)
            except Exception as e:
                logger.error('ConfigManager.load 失败: %s' % e)
        return default

    @staticmethod
    def save(cfg):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error('ConfigManager.save 失败: %s' % e)
            return False


# ============== 简易 HTTP 会话（替代 requests，纯标准库） ==============
class HttpSession:
    def __init__(self):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.cookie_handler = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        if _create_unverified_https:
            self.https_handler = urllib.request.HTTPSHandler(
                context=_create_unverified_https())
        else:
            self.https_handler = urllib.request.HTTPSHandler()
        self.opener = urllib.request.build_opener(
            self.cookie_handler, self.https_handler,
            urllib.request.HTTPRedirectHandler(),
        )
        self.default_headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

    def _decode(self, resp, data):
        encoding = resp.headers.get('Content-Encoding', '')
        if 'gzip' in encoding:
            try:
                data = gzip.decompress(data)
            except Exception:
                pass
        for enc in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode('utf-8', errors='replace')

    def get(self, url, timeout=15, extra_headers=None):
        headers = dict(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                text = self._decode(resp, raw)
                status = getattr(resp, 'status', resp.code)
                return _HttpResp(status, text, resp.headers)
        except urllib.error.HTTPError as e:
            raw = e.read() or b''
            text = ''
            try:
                text = self._decode(e, raw)
            except Exception:
                pass
            return _HttpResp(e.code, text, getattr(e, 'headers', None))

    def post(self, url, data=None, timeout=15, extra_headers=None):
        headers = dict(self.default_headers)
        body = None
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        elif isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        elif data is None:
            body = b''
            headers.setdefault('Content-Length', '0')
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                text = self._decode(resp, raw)
                status = getattr(resp, 'status', resp.code)
                return _HttpResp(status, text, resp.headers)
        except urllib.error.HTTPError as e:
            raw = e.read() or b''
            text = ''
            try:
                text = self._decode(e, raw)
            except Exception:
                pass
            return _HttpResp(e.code, text, getattr(e, 'headers', None))


class _HttpResp:
    __slots__ = ('status', 'text', 'headers')

    def __init__(self, status, text, headers):
        self.status = status
        self.text = text
        self.headers = headers


# ============== 签到核心类 ==============
class BinMTSigner:
    def __init__(self, username, password, log_callback=None):
        self.username = username
        self.password = password
        self.session = HttpSession()
        self.log_cb = log_callback or (lambda msg: None)
        # 保存最后一次详细结果（用于青龙通知汇总）
        self.last_msg = ''
        self.last_ok = False

    def log(self, msg, level='info'):
        full_msg = '[%s] %s' % (self.username, msg)
        self.log_cb(full_msg)
        getattr(logger, level)(full_msg)

    # ---------- 工具：正则提取 ----------
    @staticmethod
    def _extract(pattern, text):
        m = re.search(pattern, text, re.I | re.S)
        return m.group(1) if m else None

    # ---------- 工具：从各种响应格式提取人类可读消息 ----------
    @staticmethod
    def _extract_sign_message(text):
        if not text:
            return ''
        work = text.strip()
        m = re.search(r'<root>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</root>', work, re.I | re.S)
        if m:
            work = m.group(1).strip()
        for func_re in [
            r'''succeedhandle_[A-Za-z0-9_]*\s*\(\s*['"](.*?)['"]''',
            r'''errorhandle_[A-Za-z0-9_]*\s*\(\s*['"](.*?)['"]''',
            r'''showmessage\s*\(\s*['"](.*?)['"]''',
        ]:
            mm = re.search(func_re, work, re.S)
            if mm:
                work = mm.group(1).strip()
                break
        return work

    # ---------- 工具：判断签到响应是否成功 (Bugfix 版统一逻辑) ----------
    @staticmethod
    def _parse_sign_result(text):
        if not text:
            return False
        if re.search(r'succeedhandle_[A-Za-z0-9_]*\s*\(', text):
            return True
        if re.search(r'errorhandle_[A-Za-z0-9_]*\s*\(', text):
            return False

        msg = BinMTSigner._extract_sign_message(text)
        lower_msg = msg.lower() if msg else ''

        fail_patterns = [
            '请先登录', '需要登录', '未登录', '登录后',
            '签到失败', '签到功能', '无权', '禁止',
            '关闭', '错误', '异常', '失败',
            'login', 'error', 'fail',
        ]
        for kw in fail_patterns:
            if kw.lower() in lower_msg:
                return False

        success_patterns = [
            '今日已签', '重复签到', '已经签到', '已签到', '已签',
            '签到成功', '签到完成', '签到奖励',
            '获得', '奖励', '恭喜',
            '金币', '积分',
            '连续签到',
        ]
        for kw in success_patterns:
            if kw in msg:
                return True

        if re.search(r'\+\s*\d+', msg):
            return True

        return False

    # ---------- 登录 ----------
    def login(self):
        self.log('开始登录...')
        try:
            resp = self.session.get(LOGIN_INIT, timeout=15)
            loginhash = self._extract(r'loginhash=([A-Za-z0-9]+)"', resp.text)
            formhash = self._extract(r'name="formhash"\s+value="([a-f0-9]{8})"', resp.text)

            if not loginhash or not formhash:
                self.log('登录失败：无法提取 loginhash/formhash', 'error')
                self.last_msg = '登录参数提取失败'
                self.last_ok = False
                return False

            login_url = ('%s/member.php?mod=logging&action=login&loginsubmit=yes'
                         '&handlekey=login&loginhash=%s&inajax=1' % (BASE_URL, loginhash))
            data = {
                'formhash': formhash,
                'referer': '%s/forum.php' % BASE_URL,
                'loginfield': 'username',
                'username': self.username,
                'password': self.password,
                'questionid': '0',
                'answer': '',
            }
            resp = self.session.post(login_url, data=data, timeout=15)
            text = resp.text

            if '欢迎您回来' in text:
                name = self._extract(r'欢迎您回来，(.*?)，现在', text) or self.username
                self.log('登录成功！用户组: %s' % name)
                return True

            err = self._extract(r"errorhandle_login\('(.*?)',", text)
            msg = err or '未知原因'
            self.log('登录失败：%s' % msg, 'error')
            self.last_msg = '登录失败: %s' % msg
            self.last_ok = False
            return False

        except (urllib.error.URLError, OSError) as e:
            self.log('登录异常(网络): %s' % e, 'error')
            self.last_msg = '登录网络异常: %s' % e
            self.last_ok = False
            return False
        except Exception as e:
            self.log('登录异常: %s' % e, 'error')
            self.last_msg = '登录异常: %s' % e
            self.last_ok = False
            return False

    # ---------- 签到 ----------
    def sign_in(self):
        self.log('开始签到...')
        try:
            resp = self.session.get(SIGN_PAGE, timeout=15)
            formhash = self._extract(r'name="formhash"\s+value="([a-f0-9]{8})"', resp.text) \
                or self._extract(r'formhash=([a-f0-9]{8})', resp.text)

            if not formhash:
                if ('请先登录' in resp.text) or ('登录' in resp.text and 'formhash' not in resp.text):
                    self.log('签到失败：未登录或Cookie已过期，尝试重新登录...', 'warning')
                    if self.login():
                        return self.sign_in()
                self.log('签到失败：无法获取 formhash', 'error')
                self.last_msg = '签到失败: formhash 获取失败'
                self.last_ok = False
                return False

            sign_url = '%s&formhash=%s&format=text' % (SIGN_API, formhash)
            resp = self.session.get(sign_url, timeout=15, extra_headers={
                'Referer': SIGN_PAGE,
            })
            text = resp.text.strip()

            readable_msg = BinMTSigner._extract_sign_message(text)
            ok = BinMTSigner._parse_sign_result(text)
            self.last_ok = ok

            if ok:
                if ('今日已签' in readable_msg) or ('重复签到' in readable_msg) or ('已签' in readable_msg):
                    display = '今日已完成签到 ✓'
                    self.last_msg = '今日已完成签到'
                else:
                    if readable_msg:
                        display = '签到成功！%s' % readable_msg
                        self.last_msg = readable_msg
                    else:
                        display = '签到成功 ✓'
                        self.last_msg = '签到成功'
                self.log(display)
                return True

            if ('登录' in readable_msg) or ('login' in readable_msg.lower()):
                reason = '签到失败：需要登录'
            elif readable_msg:
                reason = '签到失败：%s' % readable_msg
            else:
                reason = '签到失败，原始响应: %s' % text[:200]
            self.log(reason, 'error')
            self.last_msg = readable_msg or reason
            return False

        except (urllib.error.URLError, OSError) as e:
            self.log('签到异常(网络): %s' % e, 'error')
            self.last_msg = '签到网络异常: %s' % e
            self.last_ok = False
            return False
        except Exception as e:
            self.log('签到异常: %s' % e, 'error')
            self.last_msg = '签到异常: %s' % e
            self.last_ok = False
            return False

    # ---------- 运行完整流程 ----------
    def run(self, delay_range=(60, 300), random_time=False):
        if random_time and delay_range[1] > delay_range[0]:
            delay = random.randint(delay_range[0], delay_range[1])
            self.log('随机延迟 %d 秒后执行签到 (防风控)...' % delay)
            time.sleep(delay)

        if self.login():
            return self.sign_in()
        return False
