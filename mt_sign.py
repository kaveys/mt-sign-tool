# -*- coding: utf-8 -*-
"""
MT论坛 (bbs.binmt.cc) 自动签到工具 —— GUI 版（单文件独立运行）
================================================================
✅ 本文件就是一个独立的脚本，不再需要 mt_sign_core.py
✅ Python 环境里直接运行: python mt_sign.py
✅ 打包成 EXE：双击即可运行，不需要任何附带文件

【打包为 单文件 Windows EXE】
先 pip install pyinstaller，然后在本文件所在目录执行（一行命令搞定）：

    pyinstaller -F -w --clean --noconfirm -n "MT论坛签到工具" --icon=icon.ico --add-data "icon.ico;." mt_sign.py

    -F                单文件打包
    -w                运行时不弹黑色命令行窗口（GUI 专用）
    -n                指定 exe 文件名
    --icon=icon.ico   让生成的 EXE 在资源管理器里显示自定义图标
    --add-data        把 icon.ico 也打包进 EXE，供运行时设置窗口标题栏图标

产物：dist\MT论坛签到工具.exe  直接拷走双击使用，账号密码保存在同目录 mt_config.json。
"""

import os
import re
import sys
import json
import time
import gzip
import random
import logging
import threading
import ssl
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime


# ====================================================================
# 资源路径解析：同时兼容「源码直接运行」与「PyInstaller 单文件打包后运行」
# ====================================================================
def _get_resource_path(relative_path: str) -> str:
    """PyInstaller 打包后运行时，资源会被解压到 sys._MEIPASS 临时目录。
    源码直接运行时，则取当前脚本所在目录。
    找不到该文件时仍返回字符串，调用方用 try/except 静默处理即可。"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller 单文件模式：运行时临时解压目录
        base = sys._MEIPASS
    else:
        # 源码直接运行：脚本所在目录
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# ====================================================================
# 【内嵌核心模块】常量 / 日志 / SSL / ConfigManager / HttpSession / BinMTSigner
# 全部代码都嵌在这里，本脚本无需任何附属 .py 文件即可独立运行
# ====================================================================

BASE_URL = 'https://bbs.binmt.cc'
SIGN_PAGE = BASE_URL + '/k_misign-sign.html'
SIGN_API = BASE_URL + '/plugin.php?id=k_misign:sign&operation=qiandao'
LOGIN_INIT = (BASE_URL + '/member.php?mod=logging&action=login&infloat=yes'
              '&handlekey=login&inajax=1&ajaxtarget=fwin_content_login')

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Safari/537.36')

# 运行目录判断：
#   - 打包后(sys.frozen=True)：使用 exe 所在目录
#   - 源码运行：使用 .py 所在目录
if getattr(sys, 'frozen', False):
    _RUN_DIR = os.path.dirname(sys.executable)
else:
    _RUN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_RUN_DIR, 'mt_config.json')
LOG_FILE = os.path.join(_RUN_DIR, 'mt_sign.log')

# ---- SSL 兼容 ----
try:
    _create_unverified_https = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https = None

# ---- 日志（文件句柄，只初始化一次） ----
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


# ---- 配置存储 ----
class ConfigManager:
    @staticmethod
    def load():
        default = {
            'accounts': [],
            'auto_start': False,
            'min_delay': 60,
            'max_delay': 300,
            'random_sign_time': False,
            'proxy_url': '',               # 新增：HTTP/HTTPS 代理
            'global_cookie_json': '',      # 新增：全局导入 Cookie JSON 字符串（每个账号可再单独配）
            'account_cookies': {},         # 新增：按账号 username -> cookie_json 字符串分桶
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    for k, v in loaded.items():
                        if k in default or isinstance(default.get(k), type(v)):
                            default[k] = v
                        else:
                            default[k] = v
            except Exception as e:
                logger.error('ConfigManager.load: %s' % e)
        return default

    @staticmethod
    def save(cfg):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error('ConfigManager.save: %s' % e)
            return False


# ---- HTTP 会话 ----
class HttpSession:
    def __init__(self, proxy_url=None):
        """proxy_url 示例: http://127.0.0.1:7890  http://user:pass@host:port"""
        cj = http.cookiejar.CookieJar()
        ch = urllib.request.HTTPCookieProcessor(cj)
        hh = (urllib.request.HTTPSHandler(context=_create_unverified_https())
              if _create_unverified_https else urllib.request.HTTPSHandler())

        handlers = [ch, hh]
        if proxy_url:
            parsed = urllib.parse.urlparse(proxy_url)
            proxies = {}
            scheme = (parsed.scheme or 'http').lower()
            if scheme in ('http', 'https'):
                proxies['http'] = proxy_url
                proxies['https'] = proxy_url
            else:
                proxies['http'] = proxy_url
                proxies['https'] = proxy_url
            handlers.insert(0, urllib.request.ProxyHandler(proxies))

        handlers.append(urllib.request.HTTPRedirectHandler())
        self.opener = urllib.request.build_opener(*handlers)
        self.cookie_jar = cj  # 暴露给外部，便于手动导入 Cookie
        self.proxy_url = proxy_url
        self.default_headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

    @staticmethod
    def _decode(resp, data):
        # 即使代理/CDN/WAF 抹掉了 Content-Encoding 响应头，也用 gzip magic bytes (0x1f 0x8b) 兜底判断
        header_enc = ''
        try:
            header_enc = (resp.headers.get('Content-Encoding', '') or '')
        except Exception:
            header_enc = ''
        is_gzip = ('gzip' in header_enc) or (len(data) >= 2 and data[0] == 0x1f and data[1] == 0x8b)
        if is_gzip:
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
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read()
                return _HttpResp(getattr(r, 'status', r.code), self._decode(r, raw), r.headers)
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
        body = b''
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        elif isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read()
                return _HttpResp(getattr(r, 'status', r.code), self._decode(r, raw), r.headers)
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


# ---- 签到核心类 ----
class BinMTSigner:
    def __init__(self, username, password, log_callback=None,
                 proxy_url=None, cookie_json=None):
        self.username = username
        self.password = password
        self.session = HttpSession(proxy_url=proxy_url)
        self.log_cb = log_callback or (lambda msg: None)
        self.last_msg = ''
        self.last_ok = False
        self._cookie_imported = False
        self._import_cookie_json(cookie_json)

    # ---- Cookie 导入（WAF 拦截时最有效：直接用已登录会话）----
    def _import_cookie_json(self, cookie_json):
        if not cookie_json:
            return
        mapping = None
        try:
            # cookie_json 可能是 dict 或者 JSON 字符串
            if isinstance(cookie_json, dict):
                mapping = cookie_json
            else:
                mapping = json.loads(str(cookie_json))
        except Exception as e:
            self.log('⚠️  导入 Cookie 失败：JSON 解析错误 %s' % e, 'error')
            return
        if not isinstance(mapping, dict):
            self.log('⚠️  导入 Cookie 失败：JSON 根对象必须是 dict', 'error')
            return

        bucket = None
        if self.username in mapping and isinstance(mapping[self.username], dict):
            bucket = mapping[self.username]
        else:
            all_dict_vals = (len(mapping) > 0 and
                             all(isinstance(v, dict) for v in mapping.values()))
            if all_dict_vals:
                self.log('⚠️  导入 Cookie 未命中账号 %s（已有的账号: %s）' % (
                    self.username, ', '.join(mapping.keys())), 'error')
                return
            bucket = mapping

        if not bucket:
            return

        domain = 'bbs.binmt.cc'
        try:
            from http.cookiejar import Cookie
            import time as _t
            now = int(_t.time())
            for k, v in bucket.items():
                if v is None:
                    continue
                key = str(k).strip()
                val = str(v).strip()
                if not key:
                    continue
                c = Cookie(
                    version=0, name=key, value=val,
                    port=None, port_specified=False,
                    domain=domain, domain_specified=True, domain_initial_dot=True,
                    path='/', path_specified=True,
                    secure=False, expires=now + 365 * 86400,
                    discard=False, comment=None, comment_url=None,
                    rest={'HttpOnly': None}, rfc2109=False,
                )
                self.session.cookie_jar.set_cookie(c)
                if not key.startswith('cQWy_') and '_' not in key and len(key) < 20:
                    c2 = Cookie(
                        version=0, name='cQWy_2132_' + key, value=val,
                        port=None, port_specified=False,
                        domain=domain, domain_specified=True, domain_initial_dot=True,
                        path='/', path_specified=True,
                        secure=False, expires=now + 365 * 86400,
                        discard=False, comment=None, comment_url=None,
                        rest={'HttpOnly': None}, rfc2109=False,
                    )
                    self.session.cookie_jar.set_cookie(c2)
            self._cookie_imported = True
            self.log('✅ 已导入 Cookie（键数 %d），登录时会先验证有效性' % len(bucket))
        except Exception as e:
            self.log('⚠️  写入 CookieJar 异常: %s' % e, 'error')

    def _verify_logged_in(self):
        try:
            resp = self.session.get(BASE_URL + '/forum.php', timeout=15,
                                    extra_headers={'Referer': BASE_URL + '/'})
            text = resp.text
            features = [
                'action=logout', 'mod=logging&action=logout', '退出',
                '我的帖子', '个人中心', '消息',
                ('<a href="home.php?mod=space&uid=' in text) or
                ('/home.php?mod=space&uid=' in text and 'class="avt"' in text),
            ]
            matched = sum(1 for f in features
                          if (f if isinstance(f, bool) else (f in text)))
            return matched >= 2
        except Exception:
            return False

    def export_cookie_dict(self):
        """导出当前 session 的 cookie 为扁平 dict（可直接写入 Cookie JSON 配置或青龙变量）"""
        out = {}
        for c in self.session.cookie_jar:
            try:
                if c.value is not None:
                    out[c.name] = c.value
            except Exception:
                pass
        return out

    def log(self, msg, level='info'):
        full_msg = '[%s] %s' % (self.username, msg)
        self.log_cb(full_msg)
        getattr(logger, level)(full_msg)

    @staticmethod
    def _extract(pattern, text):
        m = re.search(pattern, text, re.I | re.S)
        return m.group(1) if m else None

    @staticmethod
    def _unpack_inajax(text: str) -> str:
        """Discuz &inajax=1 响应会用 <root><![CDATA[ ...真实HTML... ]]></root> 包装；
        剥去 wrapper 后再匹配，避免包装壳影响提取。"""
        if not text:
            return text
        m = re.search(r'<!\[CDATA\[(.*?)\]\]>', text, re.S)
        if m:
            return m.group(1)
        m2 = re.search(r'<root>(.*)</root>', text, re.I | re.S)
        if m2:
            return m2.group(1)
        return text

    @staticmethod
    def _find_login_hashes(text: str):
        """多套正则从严格到宽松逐级尝试，兼容 Discuz 不同皮肤、inajax 包装、
        CDN 注入 JS、属性顺序变化、单双引号差异。"""
        unpacked = BinMTSigner._unpack_inajax(text)

        # —— loginhash（从严格 → 宽松）——
        loginhash = None
        for pat in [
            r'loginhash=([A-Za-z0-9]+)"',
            r"loginhash=([A-Za-z0-9]+)'",
            r'loginhash=([A-Za-z0-9]+)[&<\s]',
            r'id="loginform_([A-Za-z0-9]+)"',
            r"'loginhash'\s*[:=]\s*'([A-Za-z0-9]+)'",
        ]:
            m = re.search(pat, unpacked, re.I)
            if m:
                loginhash = m.group(1)
                break
        if not loginhash:
            m = re.search(r'loginhash=([A-Za-z0-9]+)', unpacked, re.I)
            if m: loginhash = m.group(1)
        if not loginhash:
            m = re.search(r'loginhash=([A-Za-z0-9]+)', text, re.I)
            if m: loginhash = m.group(1)

        # —— formhash（从严格 → 宽松）——
        formhash = None
        for pat in [
            r'name="formhash"\s+value="([a-f0-9]+)"',
            r"name=\"formhash\"\s+value='([a-f0-9]+)'",
            r"<input[^>]*name=[\"']formhash[\"'][^>]*value=[\"']([a-f0-9]+)[\"']",
            r"value=[\"']([a-f0-9]+)[\"'][^>]*name=[\"']formhash[\"']",
            r'formhash=([a-f0-9]+)',
            r"'formhash'\s*:\s*'([a-f0-9]+)'",
        ]:
            m = re.search(pat, unpacked, re.I)
            if m:
                formhash = m.group(1)
                break
        if not formhash:
            m = re.search(r'formhash[=:"\'\s]+([a-f0-9]{4,12})', text, re.I)
            if m: formhash = m.group(1)

        return loginhash, formhash

    @staticmethod
    def _extract_sign_message(text):
        if not text:
            return ''
        work = text.strip()
        m = re.search(r'<root>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</root>', work, re.I | re.S)
        if m:
            work = m.group(1).strip()
        for fre in [
            r'''succeedhandle_[A-Za-z0-9_]*\s*\(\s*['"](.*?)['"]''',
            r'''errorhandle_[A-Za-z0-9_]*\s*\(\s*['"](.*?)['"]''',
            r'''showmessage\s*\(\s*['"](.*?)['"]''',
        ]:
            mm = re.search(fre, work, re.S)
            if mm:
                work = mm.group(1).strip()
                break
        return work

    @staticmethod
    def _parse_sign_result(text):
        if not text:
            return False
        if re.search(r'succeedhandle_[A-Za-z0-9_]*\s*\(', text):
            return True
        if re.search(r'errorhandle_[A-Za-z0-9_]*\s*\(', text):
            return False
        msg = BinMTSigner._extract_sign_message(text)
        lower_msg = (msg or '').lower()
        for kw in ['请先登录', '需要登录', '未登录', '登录后',
                   '签到失败', '签到功能', '无权', '禁止',
                   '关闭', '错误', '异常', '失败',
                   'login', 'error', 'fail']:
            if kw.lower() in lower_msg:
                return False
        for kw in ['今日已签', '重复签到', '已经签到', '已签到', '已签',
                   '签到成功', '签到完成', '签到奖励',
                   '获得', '奖励', '恭喜', '金币', '积分',
                   '连续签到']:
            if kw in msg:
                return True
        if re.search(r'\+\s*\d+', msg):
            return True
        return False

    def login(self):
        # 0) Cookie 已导入则先验证（WAF 拦截时直接绕过登录表单）
        if self._cookie_imported:
            self.log('Cookie 已导入，先验证当前 Cookie 是否仍然有效…')
            if self._verify_logged_in():
                self.log('✅ Cookie 验证通过（已是登录状态），跳过账号密码登录')
                self.last_msg = 'Cookie 登录成功'
                return True
            self.log('⚠️  Cookie 未通过验证（可能过期或不完整），回退到账号密码登录')

        self.log('开始登录...')
        try:
            # 1) 先访问主页预热 Cookie（saltkey / sid / cdn_sec_tc / acw_tc）
            try:
                self.session.get(BASE_URL + '/forum.php', timeout=15,
                                 extra_headers={'Referer': BASE_URL + '/'})
            except Exception:
                pass

            # 2) 两套登录入口（inajax → 普通登录页），加 Referer / X-Requested-With 降低拦截率
            candidates = [
                ('LOGIN_INIT(inajax)', LOGIN_INIT, {
                    'Referer': BASE_URL + '/forum.php',
                    'X-Requested-With': 'XMLHttpRequest',
                }),
                ('普通登录页', BASE_URL + '/member.php?mod=logging&action=login', {
                    'Referer': BASE_URL + '/forum.php',
                }),
            ]
            loginhash, formhash = None, None
            last_code, last_text = 0, ''
            for label, url, extra in candidates:
                resp = self.session.get(url, timeout=15, extra_headers=extra)
                last_code, last_text = resp.status, resp.text
                lh, fh = BinMTSigner._find_login_hashes(resp.text)
                if lh and not loginhash: loginhash = lh
                if fh and not formhash: formhash = fh
                if loginhash and formhash:
                    break
                self.log(
                    '  [%s] HTTP %d  loginhash=%s  formhash=%s' % (
                        label, last_code,
                        ('✅' + loginhash) if loginhash else '❌',
                        ('✅' + (formhash[:8] if formhash else '')) if formhash else '❌',
                    )
                )

            if not loginhash or not formhash:
                self.log('登录失败：无法提取 loginhash/formhash', 'error')
                preview = (last_text or '')[:700].replace('\r', ' ').replace('\n', ' ')
                self.log('  诊断：HTTP %d  响应预览(前600字符)：%s' % (last_code, preview[:600]), 'error')
                self.log('  可能原因：①本机IP/代理被论坛CDN/WAF拦截（返回验证页而非登录页）', 'error')
                self.log('            ②响应头Content-Encoding丢失致乱码（本版已加magic bytes兜底）', 'error')
                self.log('            ③论坛临时维护/升级，HTML结构变动', 'error')
                self.last_msg = '登录参数提取失败'
                return False

            # 3) 提交登录
            login_url = (BASE_URL + '/member.php?mod=logging&action=login&loginsubmit=yes'
                         '&handlekey=login&loginhash=%s&inajax=1' % loginhash)
            data = {
                'formhash': formhash,
                'referer': BASE_URL + '/forum.php',
                'loginfield': 'username',
                'username': self.username,
                'password': self.password,
                'questionid': '0',
                'answer': '',
            }
            resp = self.session.post(login_url, data=data, timeout=15,
                                     extra_headers={'Referer': LOGIN_INIT})
            text = resp.text
            if '欢迎您回来' in text:
                name = self._extract(r'欢迎您回来，(.*?)，现在', text) or self.username
                self.log('登录成功！用户组: %s' % name)
                return True
            err = self._extract(r"errorhandle_login\('(.*?)',", text)
            if not err:
                err = self._extract(r"errorhandle_login\('(.*?)',", BinMTSigner._unpack_inajax(text))
            msg = err or ('未知原因 (响应预览: %s)' % text[:200].replace('\r', ' ').replace('\n', ' '))
            self.log('登录失败：%s' % msg, 'error')
            self.last_msg = '登录失败: %s' % msg
            return False
        except (urllib.error.URLError, OSError) as e:
            self.log('登录异常(网络): %s' % e, 'error')
            self.last_msg = '登录网络异常: %s' % e
            return False
        except Exception as e:
            self.log('登录异常: %s' % e, 'error')
            self.last_msg = '登录异常: %s' % e
            return False

    def sign_in(self):
        self.log('开始签到...')
        try:
            resp = self.session.get(SIGN_PAGE, timeout=15)
            formhash = (self._extract(r'name="formhash"\s+value="([a-f0-9]{8})"', resp.text)
                        or self._extract(r'formhash=([a-f0-9]{8})', resp.text))
            if not formhash:
                if ('请先登录' in resp.text) or ('登录' in resp.text and 'formhash' not in resp.text):
                    self.log('签到失败：未登录或Cookie已过期，尝试重新登录...', 'warning')
                    if self.login():
                        return self.sign_in()
                self.log('签到失败：无法获取 formhash', 'error')
                self.last_msg = '签到失败: formhash 获取失败'
                return False

            sign_url = '%s&formhash=%s&format=text' % (SIGN_API, formhash)
            resp = self.session.get(sign_url, timeout=15, extra_headers={'Referer': SIGN_PAGE})
            text = resp.text.strip()

            readable_msg = BinMTSigner._extract_sign_message(text)
            ok = BinMTSigner._parse_sign_result(text)
            self.last_ok = ok

            if ok:
                if ('今日已签' in readable_msg) or ('重复签到' in readable_msg) or ('已签' in readable_msg):
                    display, self.last_msg = '今日已完成签到 ✓', '今日已完成签到'
                elif readable_msg:
                    display, self.last_msg = '签到成功！%s' % readable_msg, readable_msg
                else:
                    display, self.last_msg = '签到成功 ✓', '签到成功'
                self.log(display)
                return True

            if ('登录' in readable_msg) or ('login' in (readable_msg or '').lower()):
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
            return False
        except Exception as e:
            self.log('签到异常: %s' % e, 'error')
            self.last_msg = '签到异常: %s' % e
            return False

    def run(self, delay_range=(60, 300), random_time=False):
        if random_time and delay_range[1] > delay_range[0]:
            delay = random.randint(delay_range[0], delay_range[1])
            self.log('随机延迟 %d 秒后执行签到 (防风控)...' % delay)
            time.sleep(delay)
        if self.login():
            return self.sign_in()
        return False


# ====================================================================
#  GUI 界面（Tkinter）
# ====================================================================
class MTSignApp:
    def __init__(self, root):
        self.root = root
        self.root.title('MT论坛 自动签到工具 v1.2（单文件版）')
        self.root.geometry('760x580')
        self.root.minsize(680, 500)

        # 窗口图标（兼容 PyInstaller 打包后运行 + 源码直接运行；找不到图标则静默忽略）
        try:
            icon_path = _get_resource_path('icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        self.config = ConfigManager.load()
        self.running = False

        self._build_style()
        self._build_ui()
        self._refresh_accounts()

        if self.config.get('auto_start'):
            self.root.after(1500, self._start_sign_thread)

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TButton', padding=6, font=('微软雅黑', 9))
        style.configure('Title.TLabel', font=('微软雅黑', 12, 'bold'))
        style.configure('Accent.TButton', padding=8)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(top, text='MT论坛 自动签到工具', style='Title.TLabel').pack(side=tk.LEFT)
        ttk.Label(top, text=BASE_URL, foreground='#666').pack(side=tk.LEFT, padx=15)
        ttk.Label(top, text='  单文件版 · 零依赖', foreground='#2f9e44').pack(side=tk.LEFT)

        # 账号管理
        acc_frame = ttk.LabelFrame(main, text='账号管理', padding=8)
        acc_frame.pack(fill=tk.X, pady=(0, 8))

        input_row = ttk.Frame(acc_frame)
        input_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(input_row, text='用户名:').pack(side=tk.LEFT)
        self.ent_user = ttk.Entry(input_row, width=18)
        self.ent_user.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(input_row, text='密码:').pack(side=tk.LEFT)
        self.ent_pwd = ttk.Entry(input_row, width=18, show='●')
        self.ent_pwd.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(input_row, text='➕ 添加账号', command=self._add_account).pack(side=tk.LEFT)

        list_frame = ttk.Frame(acc_frame)
        list_frame.pack(fill=tk.X)
        cols = ('idx', 'username', 'last_sign', 'status')
        self.tree = ttk.Treeview(list_frame, columns=cols, show='headings', height=5)
        for col, w, t in [('idx', 40, '#'), ('username', 160, '用户名'),
                          ('last_sign', 220, '上次签到'), ('status', 140, '状态')]:
            self.tree.heading(col, text=t)
            self.tree.column(col, width=w, anchor='w')
        self.tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        btn_row = ttk.Frame(acc_frame)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text='🗑 删除选中', command=self._del_account).pack(side=tk.LEFT)
        ttk.Button(btn_row, text='👁 显示/隐藏密码', command=self._toggle_pwd).pack(side=tk.LEFT, padx=8)

        # 设置
        set_frame = ttk.LabelFrame(main, text='签到设置', padding=8)
        set_frame.pack(fill=tk.X, pady=(0, 8))

        self.var_auto = tk.BooleanVar(value=self.config.get('auto_start', False))
        self.var_rand = tk.BooleanVar(value=self.config.get('random_sign_time', False))
        self.var_min = tk.IntVar(value=self.config.get('min_delay', 60))
        self.var_max = tk.IntVar(value=self.config.get('max_delay', 300))
        self.var_proxy = tk.StringVar(value=self.config.get('proxy_url', '') or '')

        r1 = ttk.Frame(set_frame)
        r1.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(r1, text='启动程序时自动签到', variable=self.var_auto).pack(side=tk.LEFT)
        ttk.Checkbutton(r1, text='启用随机延迟（防风控，推荐开启）',
                        variable=self.var_rand).pack(side=tk.LEFT, padx=20)

        r2 = ttk.Frame(set_frame)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text='延迟范围(秒):').pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=0, to=3600, width=7, textvariable=self.var_min).pack(side=tk.LEFT, padx=4)
        ttk.Label(r2, text=' ~ ').pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=0, to=7200, width=7, textvariable=self.var_max).pack(side=tk.LEFT, padx=4)
        ttk.Button(r2, text='💾 保存设置', command=self._save_settings).pack(side=tk.RIGHT)

        # 代理 + Cookie 导入 Tab（嵌套 Notebook，保持界面整洁）
        adv_nb = ttk.Notebook(set_frame)
        adv_nb.pack(fill=tk.X, pady=(6, 0))

        # Tab 1: 代理设置
        tab_proxy = ttk.Frame(adv_nb, padding=6)
        adv_nb.add(tab_proxy, text=' 🌐 代理出口 ')
        ttk.Label(tab_proxy,
                  text='HTTP/HTTPS 代理（当本机/青龙服务器 IP 被论坛 CDN/WAF 拦截时使用）：').pack(
            anchor=tk.W)
        proxy_row = ttk.Frame(tab_proxy)
        proxy_row.pack(fill=tk.X, pady=4)
        ttk.Entry(proxy_row, textvariable=self.var_proxy,
                  font=('Consolas', 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Label(proxy_row,
                  text='示例: http://127.0.0.1:7890  |  http://user:pwd@host:port  |  host:port（默认 http）',
                  foreground='#666').pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(tab_proxy,
                  text='💡 小提示：买便宜的「住宅代理」或「家庭宽带出口代理」效果最好，云IP容易继续被识别。\n'
                       '        SOCKS5 不支持，可在本机用 V2Ray/clash 转成 HTTP 代理再填入。',
                  foreground='#495057').pack(anchor=tk.W, pady=(4, 0))

        # Tab 2: Cookie 导入 / 导出
        tab_ck = ttk.Frame(adv_nb, padding=6)
        adv_nb.add(tab_ck, text=' 🍪 Cookie 导入 ')
        ttk.Label(tab_ck,
                  text='「终极兜底方案」：直接把已登录状态的 Cookie 导入会话（连登录步骤都跳过，WAF 再怎么拦也能签到）。',
                  foreground='#7048e8').pack(anchor=tk.W)
        ck_top = ttk.Frame(tab_ck)
        ck_top.pack(fill=tk.X, pady=6)
        ttk.Label(ck_top, text='全局 Cookie JSON（所有账号都应用，优先级低于「账号专属」）：').pack(anchor=tk.W)
        self.txt_gcookie = scrolledtext.ScrolledText(ck_top, height=4, font=('Consolas', 9),
                                                     wrap=tk.WORD, bg='#f8f9fa')
        self.txt_gcookie.pack(fill=tk.X, pady=2)
        self.txt_gcookie.insert('1.0', self.config.get('global_cookie_json', '') or '')
        ttk.Label(tab_ck,
                  text='支持两种 JSON 格式（键可用 Discuz 长名或短名，短名会自动补 cQWy_2132_ 前缀）：\n'
                       ' ① 扁平：{"saltkey":"xxx","auth":"xxx","ulastactivity":"xxx"}\n'
                       ' ② 分桶：{"Kaveys":{"saltkey":"xxx","auth":"xxx"},"user2":{...}}').pack(
            anchor=tk.W, pady=(4, 0), foreground='#495057')

        btn_row2 = ttk.Frame(tab_ck)
        btn_row2.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row2, text='🔍 格式示例',
                   command=self._cookie_help_example).pack(side=tk.LEFT)
        ttk.Button(btn_row2, text='📋 粘贴选中账号的 Cookie',
                   command=self._paste_account_cookie_from_clipboard).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row2, text='⬇️ 导出选中账号的 Cookie',
                   command=self._export_account_cookie_to_clipboard).pack(side=tk.LEFT, padx=6)
        ttk.Label(btn_row2,
                  text='（导出功能会运行一次完整签到，成功后把当前会话里的 Cookie 复制到剪贴板）',
                  foreground='#868e96').pack(side=tk.LEFT, padx=10)

        # 执行
        exec_row = ttk.Frame(main)
        exec_row.pack(fill=tk.X, pady=(0, 8))
        self.btn_run = ttk.Button(exec_row, text='▶ 开始签到', style='Accent.TButton',
                                   command=self._start_sign_thread)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_stop = ttk.Button(exec_row, text='■ 停止', command=self._stop_sign, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)
        ttk.Label(exec_row, text='请勿在凌晨0点集中签到，避免给服务器造成瞬时压力',
                  foreground='#c92a2a').pack(side=tk.RIGHT)

        # 日志
        log_frame = ttk.LabelFrame(main, text='运行日志', padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.txt_log = scrolledtext.ScrolledText(
            log_frame, height=12, wrap=tk.WORD,
            font=('Consolas', 9), bg='#1e1e1e', fg='#d4d4d4',
            insertbackground='#d4d4d4',
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.tag_configure('ok', foreground='#6ec673')
        self.txt_log.tag_configure('warn', foreground='#e8c27a')
        self.txt_log.tag_configure('err', foreground='#f28779')

    # ---- 日志 ----
    def _log(self, msg, tag=None):
        ts = datetime.now().strftime('%H:%M:%S')
        line = '[%s] %s\n' % (ts, msg)
        self.txt_log.insert(tk.END, line, tag)
        self.txt_log.see(tk.END)
        self.root.update_idletasks()

    # ---- 账号管理 ----
    def _refresh_accounts(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, acc in enumerate(self.config['accounts'], 1):
            self.tree.insert('', tk.END, iid=str(idx - 1), values=(
                idx, acc.get('username', ''),
                acc.get('last_sign', '--'),
                '已启用' if acc.get('state', 1) else '已停用',
            ))

    def _add_account(self):
        u = self.ent_user.get().strip()
        p = self.ent_pwd.get().strip()
        if not u or not p:
            messagebox.showwarning('提示', '请输入用户名和密码')
            return
        for acc in self.config['accounts']:
            if acc['username'] == u:
                if not messagebox.askyesno('确认', '账号【%s】已存在，是否更新密码？' % u):
                    return
                acc['password'] = p
                break
        else:
            self.config['accounts'].append({
                'username': u, 'password': p, 'state': 1, 'last_sign': '--'
            })
        ConfigManager.save(self.config)
        self.ent_user.delete(0, tk.END)
        self.ent_pwd.delete(0, tk.END)
        self._refresh_accounts()
        self._log('已添加/更新账号: %s' % u, 'ok')

    def _del_account(self):
        sel = self.tree.selection()
        if not sel:
            return
        idxs = sorted([int(i) for i in sel], reverse=True)
        names = [self.config['accounts'][i]['username'] for i in idxs]
        if not messagebox.askyesno('确认删除', '确定删除账号: %s ?' % ', '.join(names)):
            return
        for i in idxs:
            del self.config['accounts'][i]
        ConfigManager.save(self.config)
        self._refresh_accounts()
        self._log('已删除账号: %s' % ', '.join(names), 'warn')

    def _toggle_pwd(self):
        self.ent_pwd.config(show='' if self.ent_pwd.cget('show') else '●')

    # ---- 设置 ----
    def _save_settings(self):
        mn, mx = int(self.var_min.get()), int(self.var_max.get())
        if mn > mx:
            mn, mx = mx, mn
        gcookie_text = (self.txt_gcookie.get('1.0', tk.END) or '').strip()
        # 校验 global_cookie_json：如果非空，尝试解析成 JSON（避免手滑写错）
        if gcookie_text:
            try:
                j = json.loads(gcookie_text)
                if not isinstance(j, dict):
                    raise ValueError('根对象必须是 dict')
                gcookie_text = json.dumps(j, ensure_ascii=False)  # 重新格式化
            except Exception as e:
                messagebox.showerror('Cookie JSON 格式错误',
                                     '全局 Cookie JSON 解析失败：\n%s\n\n请重新检查格式（按钮「格式示例」可复制模板）。' % e)
                return
        self.config.update({
            'auto_start': bool(self.var_auto.get()),
            'random_sign_time': bool(self.var_rand.get()),
            'min_delay': mn,
            'max_delay': mx,
            'proxy_url': (self.var_proxy.get() or '').strip(),
            'global_cookie_json': gcookie_text,
        })
        if 'account_cookies' not in self.config:
            self.config['account_cookies'] = {}
        if ConfigManager.save(self.config):
            self._log('设置已保存 ✓（含代理 & Cookie 配置）', 'ok')
            messagebox.showinfo('提示', '设置保存成功')
        else:
            messagebox.showerror('错误', '设置保存失败，请检查权限')

    # ---- Cookie 导入相关小工具 ----
    def _cookie_help_example(self):
        msg = ('两种合法的 Cookie JSON：\n\n'
               '【① 扁平 / 全局 / 单账号】\n'
               '  {\n'
               '    "saltkey": "AbCd1234",\n'
               '    "auth":     "9f8a7b6c....xxxx",\n'
               '    "ulastactivity": "12345678"\n'
               '  }\n\n'
               ' （saltkey/auth 等短名会自动补成 cQWy_2132_saltkey；\n'
               '   你也可以直接写完整键名："cQWy_2132_saltkey"）\n\n'
               '【② 按账号分桶】\n'
               '  {\n'
               '    "Kaveys": {\n'
               '        "saltkey": "xxxx",\n'
               '        "auth":    "yyyy"\n'
               '    },\n'
               '    "张三":   {"saltkey": "..."}\n'
               '  }\n\n'
               '获取 Cookie 的最简单方法：\n'
               ' 1) 在浏览器（Chrome/Edge/Firefox）登录 bbs.binmt.cc\n'
               ' 2) F12 → 应用 → Cookie → https://bbs.binmt.cc\n'
               ' 3) 复制 cQWy_2132_ 开头的所有键值，粘到上面格式里\n'
               ' 4) 最小必须包含：saltkey + auth 两个键')
        messagebox.showinfo('Cookie JSON 格式示例', msg)

    def _selected_username(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning('提示', '请先在上方账号列表中选中一个账号')
            return None
        idx = int(sel[0])
        return self.config['accounts'][idx]['username']

    def _paste_account_cookie_from_clipboard(self):
        u = self._selected_username()
        if not u:
            return
        try:
            txt = self.root.clipboard_get().strip()
        except Exception:
            messagebox.showwarning('提示', '剪贴板为空或不可读')
            return
        if not txt:
            messagebox.showwarning('提示', '剪贴板为空')
            return
        try:
            obj = json.loads(txt)
            if not isinstance(obj, dict):
                raise ValueError('根对象必须是 dict')
        except Exception as e:
            messagebox.showerror('格式错误', '剪贴板内容不是合法 JSON dict：\n%s' % e)
            return
        if 'account_cookies' not in self.config or not isinstance(self.config['account_cookies'], dict):
            self.config['account_cookies'] = {}
        self.config['account_cookies'][u] = json.dumps(obj, ensure_ascii=False)
        ConfigManager.save(self.config)
        self._log('已为账号【%s】粘贴账号专属 Cookie（%d 个键）' % (u, len(obj)), 'ok')

    def _export_account_cookie_to_clipboard(self):
        """GUI 版：选中某个账号，后台用当前配置跑一次签到，成功后复制 session Cookie 到剪贴板。
        典型场景：用户家里电脑能成功登录（家庭宽带不被拦截），导出 Cookie 后粘到青龙版里。"""
        u = self._selected_username()
        if not u:
            return
        acc = next((a for a in self.config['accounts'] if a['username'] == u), None)
        if not acc:
            return
        if not messagebox.askyesno(
                '确认导出',
                '将以账号【%s】运行一次完整「预热Cookie → 登录 → 签到流程」，\n'
                '成功后把当前会话 Cookie 复制到剪贴板。继续？' % u):
            return

        proxy_url = (self.config.get('proxy_url', '') or '').strip()
        if proxy_url and '://' not in proxy_url:
            proxy_url = 'http://' + proxy_url
        gcookie_txt = (self.config.get('global_cookie_json', '') or '').strip()
        acc_cookie_txt = (self.config.get('account_cookies', {}) or {}).get(u, '') if isinstance(
            self.config.get('account_cookies'), dict) else ''

        def do_export():
            merged = acc_cookie_txt or gcookie_txt or None
            signer = BinMTSigner(acc['username'], acc['password'],
                                 log_callback=lambda m: self.root.after(0, self._log, m),
                                 proxy_url=proxy_url or None,
                                 cookie_json=merged)
            try:
                ok = signer.run(delay_range=(1, 2), random_time=False)
            except Exception as ex:
                self._log('导出 Cookie 时异常: %s' % ex, 'err')
                self.root.after(0, lambda: messagebox.showerror('错误', str(ex)))
                return
            if not ok:
                self._log('账号【%s】签到失败，无法导出有效 Cookie（%s）' % (u, signer.last_msg), 'err')
                self.root.after(0, lambda: messagebox.showerror(
                    '导出失败', '签到未成功，当前 Cookie 可能无效：\n' + signer.last_msg))
                return
            cd = signer.export_cookie_dict()
            if not cd or len(cd) < 2:
                self.root.after(0, lambda: messagebox.showerror('导出失败', '未拿到足够的 Cookie（< 2 个）'))
                return
            payload = json.dumps(cd, ensure_ascii=False, indent=2)
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(payload)
                self.root.update()
            except Exception as ex:
                self._log('写入剪贴板失败: %s' % ex, 'err')
                return
            self._log('✅ 账号【%s】Cookie 已复制到剪贴板（共 %d 个键），可直接粘贴到青龙 MT_BBS_COOKIE_JSON 变量' % (
                u, len(cd)), 'ok')
            self.root.after(0, lambda: messagebox.showinfo(
                '导出成功',
                'Cookie（%d 键）已复制到剪贴板。\n\n'
                '【用法一 · 青龙】粘贴到青龙环境变量 MT_BBS_COOKIE_JSON\n'
                '【用法二 · GUI】粘贴到本界面 Cookie Tab 的「全局 Cookie JSON」或「账号专属」' % len(cd)))

        threading.Thread(target=do_export, daemon=True).start()

    # ---- 执行 ----
    def _start_sign_thread(self):
        if self.running:
            return
        if not self.config['accounts']:
            messagebox.showwarning('提示', '请先添加账号')
            return
        self.running = True
        self.btn_run.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        threading.Thread(target=self._run_sign_all, daemon=True).start()

    def _stop_sign(self):
        self.running = False
        self._log('已请求停止，当前账号处理完后将退出...', 'warn')

    def _update_account_status(self, idx, status):
        acc = self.config['accounts'][idx]
        acc['last_sign'] = '%s | %s' % (datetime.now().strftime('%Y-%m-%d %H:%M'), status)
        ConfigManager.save(self.config)
        self.root.after(0, self._refresh_accounts)

    def _run_sign_all(self):
        accounts = self.config['accounts']
        delay_range = (int(self.var_min.get()), int(self.var_max.get()))
        use_rand = bool(self.var_rand.get())

        self._log('=' * 50)
        self._log('开始执行签到任务，共 %d 个账号' % len(accounts))
        if use_rand:
            self._log('已启用随机延迟: %d~%d 秒' % (delay_range[0], delay_range[1]))
        self._log('=' * 50)

        ok = 0
        # 预合并 Cookie：global_cookie_json（dict/JSON字符串或空）+ account_cookies
        global_cj_raw = self.config.get('global_cookie_json', '') or ''
        account_cjs_map = self.config.get('account_cookies', {}) or {}
        proxy_url = (self.config.get('proxy_url', '') or '').strip()
        if proxy_url and '://' not in proxy_url:
            proxy_url = 'http://' + proxy_url

        for idx, acc in enumerate(accounts):
            if not self.running:
                break
            if acc.get('state', 1) != 1:
                self._log('跳过停用账号: %s' % acc['username'])
                continue
            try:
                # —— 合并 Cookie：优先账号专属 Cookie，其次全局 Cookie ——
                merged_cookie = None
                account_cj_raw = account_cjs_map.get(acc['username'], '') if isinstance(account_cjs_map, dict) else ''
                if account_cj_raw:
                    merged_cookie = account_cj_raw
                elif global_cj_raw:
                    merged_cookie = global_cj_raw
                signer = BinMTSigner(
                    acc['username'], acc['password'],
                    log_callback=lambda m: self.root.after(0, self._log, m),
                    proxy_url=proxy_url or None,
                    cookie_json=merged_cookie or None,
                )
                result = signer.run(delay_range=delay_range, random_time=use_rand)
                if result:
                    ok += 1
                    self._update_account_status(idx, '签到成功 ✓')
                    # 成功后，若用户开启了"自动记录Cookie"（先写进配置），则保存
                    if signer.session.cookie_jar:
                        try:
                            new_cd = signer.export_cookie_dict()
                            if new_cd and len(new_cd) >= 3:
                                if not isinstance(account_cjs_map, dict):
                                    account_cjs_map = {}
                                account_cjs_map[acc['username']] = json.dumps(
                                    new_cd, ensure_ascii=False)
                                self.config['account_cookies'] = account_cjs_map
                        except Exception:
                            pass
                else:
                    self._update_account_status(idx, '签到失败 ✗')
            except Exception as e:
                self._log('[%s] 任务异常: %s' % (acc['username'], e), 'err')
                self._update_account_status(idx, '异常')

            if idx < len(accounts) - 1 and self.running:
                time.sleep(random.randint(2, 6))

        self._log('=' * 50)
        if ok == len(accounts) and ok > 0:
            self._log('全部完成: %d/%d 成功 ✓' % (ok, len(accounts)), 'ok')
        elif ok > 0:
            self._log('部分完成: %d/%d 成功' % (ok, len(accounts)), 'warn')
        else:
            self._log('全部失败: %d/%d 成功' % (ok, len(accounts)), 'err')
        self._log('=' * 50)

        self.running = False
        self.btn_run.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)


# ================================================================
# 入口
# ================================================================
def main():
    root = tk.Tk()
    try:
        if sys.platform.startswith('win'):
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
    except Exception:
        pass
    MTSignApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
