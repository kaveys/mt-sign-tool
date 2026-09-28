# -*- coding: utf-8 -*-
"""
MT论坛 (bbs.binmt.cc) 自动签到 —— 青龙面板专用版（单文件独立运行）
================================================================
✅ 本脚本就是一个独立文件！青龙里只需上传 mt_sign_qinglong.py，不再需要其他任何文件
✅ 账号密码全部通过 青龙环境变量 填写（零改代码）
✅ 零第三方依赖（纯 Python 标准库），青龙默认 Python 环境直接能跑
✅ 完美适配青龙通知（Server酱 / PushPlus / Bark / 钉钉 / 企业微信 / Telegram 等）

============================================================
【青龙面板使用步骤】
============================================================

Step 1. 上传脚本
    把本文件（mt_sign_qinglong.py）上传到青龙面板的 scripts 目录即可。
    ⚠️  不需要 上传 mt_sign_core.py，本文件已把所有核心代码内嵌！

Step 2. 青龙环境变量 —— 填写账号（三选一）
┌────────────────────┬──────────────────────────────────────────────┐
│ 变量名              │ 格式 / 示例                                 │
├────────────────────┼──────────────────────────────────────────────┤
│ ✅ MT_BBS_ACCOUNTS  │ 多账号：user1#pwd1 & user2|pwd2             │
│ (推荐，兼容性最好)  │ 账号间分隔符：  &  或  换行                  │
│                    │ 账号内分隔符：  #   |   @@  ----  :::  任一  │
│                    │ 例：张三#abc123&李四|qwe456                │
├────────────────────┼──────────────────────────────────────────────┤
│ MT_BBS_USER +      │ 单账号：两个变量分别填                       │
│ MT_BBS_PASSWORD    │ 例 MT_BBS_USER=张三   MT_BBS_PASSWORD=abc123 │
├────────────────────┼──────────────────────────────────────────────┤
│ MT_BBS_JSON        │ JSON 数组（代码里精确控制）                   │
│                    │ [{"username":"张三","password":"abc123"}]    │
└────────────────────┴──────────────────────────────────────────────┘

Step 3.（可选）控制类环境变量（不设也有安全默认值）
    MT_BBS_RANDOM_DELAY   = true       # 签到前随机延迟？默认 true
    MT_BBS_DELAY_MIN      = 60         # 最小延迟(秒) 默认 60
    MT_BBS_DELAY_MAX      = 300        # 最大延迟(秒) 默认 300
    MT_BBS_NOTIFY         = fail       # always/fail/never
                                        always=总推 | fail=失败或部分才推(默认) | never=不推
    MT_BBS_INTERVAL_MIN   = 2          # 多账号间隔最小秒 默认 2
    MT_BBS_INTERVAL_MAX   = 6          # 多账号间隔最大秒 默认 6

Step 4. 青龙任务
    命令/脚本： task mt_sign_qinglong.py
    定时规则： 0 10 8 * * ?      ← 推荐 每天 8:10 执行，避开 0 点高压期
               （cron 6 位: 秒 分 时 日 月 周）

Step 5. 通知
    青龙面板里 → 系统设置 → 通知设置  配置好你要的推送渠道
    脚本会自动按三级 fallback 链调用：
      ① from notify import send  (经典 notify.py, 兼容所有渠道)
      ② ql notify -t title -c content  (青龙 3.x CLI 通知)
      ③ notify 命令 (部分改版面板)
      ④ print 回退 —— 即使没配置推送，青龙日志里也能看到明细
============================================================
"""

import os
import re
import sys
import json
import time
import gzip
import random
import ssl
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import shutil
import subprocess
from datetime import datetime

# ====================================================================
# 【内嵌核心签到模块】常量 / SSL / HTTP / BinMTSigner 全部代码都嵌在此处
# 本脚本无需任何外部 .py 文件依赖，单文件就能跑
# ====================================================================

BASE_URL = 'https://bbs.binmt.cc'
SIGN_PAGE = BASE_URL + '/k_misign-sign.html'
SIGN_API = BASE_URL + '/plugin.php?id=k_misign:sign&operation=qiandao'
LOGIN_INIT = (BASE_URL + '/member.php?mod=logging&action=login&infloat=yes'
              '&handlekey=login&inajax=1&ajaxtarget=fwin_content_login')

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Safari/537.36')

# ---- SSL 兼容 ----
try:
    _create_unverified_https = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https = None


# ---- HTTP 会话 ----
class _HttpSession:
    def __init__(self, proxy_url=None):
        """proxy_url 格式示例:
            http://127.0.0.1:7890
            http://user:pass@host:port
            https://host:port
        urllib 不原生支持 socks5；如需 socks5，可先在本机转成 HTTP 代理（如 V2Ray 的 http 入站 127.0.0.1:10809）。"""
        cj = http.cookiejar.CookieJar()
        ch = urllib.request.HTTPCookieProcessor(cj)
        hh = (urllib.request.HTTPSHandler(context=_create_unverified_https())
              if _create_unverified_https else urllib.request.HTTPSHandler())

        handlers = [ch, hh]
        if proxy_url:
            # urllib.request.ProxyHandler 的 key 是 scheme，不带 "://"
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
                return (getattr(r, 'status', r.code),
                        self._decode(r, raw), r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read() or b''
            text = ''
            try:
                text = self._decode(e, raw)
            except Exception:
                pass
            return (e.code, text, getattr(e, 'headers', None))

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
                return (getattr(r, 'status', r.code),
                        self._decode(r, raw), r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read() or b''
            text = ''
            try:
                text = self._decode(e, raw)
            except Exception:
                pass
            return (e.code, text, getattr(e, 'headers', None))


# ---- 签到核心类 ----
class BinMTSigner:
    def __init__(self, username, password, log_callback=None,
                 proxy_url=None, cookie_json=None):
        self.username = username
        self.password = password
        self.session = _HttpSession(proxy_url=proxy_url)
        self.log_cb = log_callback or (lambda msg: None)
        self.last_msg = ''
        self.last_ok = False
        self._cookie_imported = False  # 手动导入过 Cookie 后设为 True
        self._import_cookie_json(cookie_json)

    # ---- Cookie 导入（绕过 WAF / 直接用已登录会话）----
    def _import_cookie_json(self, cookie_json):
        """cookie_json 支持两种格式：
        1) 扁平 dict（单账号场景 / 多个账号共用一个 cookie 时）
           {"cQWy_2132_saltkey":"xxx","cQWy_2132_auth":"xxx","cQWy_2132_ulastactivity":"xxx", ...}
        2) 按 username 分桶 dict
           {"Kaveys": {"saltkey":"xxx","auth":"xxx"}, "user2": {...}}
        导入后设置 _cookie_imported = True；后续登录时会先验证 Cookie 是否有效。
        """
        if not cookie_json:
            return
        mapping = None
        try:
            mapping = json.loads(cookie_json)
        except Exception as e:
            self.log('⚠️  导入 Cookie 失败：JSON 解析错误 %s' % e, 'error')
            return
        if not isinstance(mapping, dict):
            self.log('⚠️  导入 Cookie 失败：JSON 根对象必须是 dict', 'error')
            return

        # 先尝试按 username 取桶（第2种格式）
        bucket = None
        if self.username in mapping and isinstance(mapping[self.username], dict):
            bucket = mapping[self.username]
        else:
            # 如果所有 value 都是 dict，视为「按账号分桶」但没找到当前用户名 → 放弃
            all_dict_vals = all(isinstance(v, dict) for v in mapping.values()) and len(mapping) > 0
            if all_dict_vals:
                self.log('⚠️  导入 Cookie 未命中账号 %s（已有的账号: %s）' % (
                    self.username, ', '.join(mapping.keys())), 'error')
                return
            # 否则：第1种格式 —— 扁平 dict，直接使用
            bucket = mapping

        if not bucket:
            return

        # 写入 cookiejar（discuz cookie 的 domain=bbs.binmt.cc，path=/）
        domain = 'bbs.binmt.cc'
        try:
            from http.cookiejar import Cookie
            import calendar
            import time as _t
            now = int(_t.time())
            for k, v in bucket.items():
                if v is None:
                    continue
                key = str(k).strip()
                val = str(v).strip()
                if not key:
                    continue
                # Discuz 的 cookie 键经常省略前缀 cQWy_2132_（GUI 导出时方便用户省略前缀，自动补全）
                if '_' not in key and not key.startswith('cQWy') and len(key) < 30:
                    for pfx in ('cQWy_2132_',):
                        candidate = pfx + key
                        # 不会重复添加，后面实际看效果
                    # 简单处理：用原名，再额外加一个补全后的名字
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
                # 如果用户给的是短键名（saltkey / auth 等），额外再补一份带 Discuz 前缀的
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
        """用当前 session 的 cookies 请求主页/签到页，判断是否已经登录。
        判断依据：页面里包含 Discuz 已登录的特征（退出链接 / 用户名 / UID）。"""
        try:
            _, text, _ = self.session.get(
                BASE_URL + '/forum.php', timeout=15,
                extra_headers={'Referer': BASE_URL + '/'})
            # 关键字：退出 / member.php?mod=logging&action=logout / 用户名出现在欢迎区 / space-uid-
            features = [
                'action=logout',
                'mod=logging&action=logout',
                '退出',
                '我的帖子',
                '个人中心',
                '消息',
                # 登录后导航区通常有用户名
                ('<a href="home.php?mod=space&uid=' in text) or
                ('/home.php?mod=space&uid=' in text and 'class="avt"' in text),
            ]
            matched = sum(1 for f in features if (f if isinstance(f, bool) else (f in text)))
            return matched >= 2
        except Exception:
            return False

    def log(self, msg, level='info'):
        full_msg = '[%s] %s' % (self.username, msg)
        self.log_cb(full_msg)

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
        # ============================================================
        # 0) 如果已经手动导入 Cookie，先验证是否仍然有效 —— 直接绕过登录表单（WAF拦截场景最常用）
        # ============================================================
        if self._cookie_imported:
            self.log('Cookie 已导入，先验证当前 Cookie 是否仍然有效…')
            if self._verify_logged_in():
                self.log('✅ Cookie 验证通过（已是登录状态），跳过账号密码登录')
                self.last_msg = 'Cookie 登录成功'
                return True
            self.log('⚠️  Cookie 未通过验证（可能过期或不完整），回退到账号密码登录')

        self.log('开始登录...')
        try:
            # ============================================================
            # 1) 先访问主页预热 Cookie（saltkey / sid / cdn_sec_tc / acw_tc）
            #    Discuz 部分部署的 loginhash 会绑定已存在的会话；
            #    若缺少这些 cookie，登录页很可能返回空壳，导致 loginhash/formhash 提取失败。
            # ============================================================
            try:
                self.session.get(BASE_URL + '/forum.php', timeout=15,
                                 extra_headers={'Referer': BASE_URL + '/'})
            except Exception:
                pass  # 主页失败也要继续尝试后续步骤（可能只是 cookie 拿不到，但后面仍能登录）

            # ============================================================
            # 2) 两套登录入口（从 inajax → 普通登录页），合并两页中提取的参数
            #    青龙服务器常在云厂商IP段，可能被 CDN/WAF 做手脚；
            #    加 Referer 和 X-Requested-With 降低被拦截概率。
            # ============================================================
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
                code, text, _ = self.session.get(url, timeout=15, extra_headers=extra)
                last_code, last_text = code, text
                lh, fh = BinMTSigner._find_login_hashes(text)
                if lh and not loginhash: loginhash = lh
                if fh and not formhash: formhash = fh
                if loginhash and formhash:
                    break
                self.log(
                    '  [%s] HTTP %d  loginhash=%s  formhash=%s' % (
                        label, code,
                        ('✅' + loginhash) if loginhash else '❌',
                        ('✅' + (formhash[:8] if formhash else '')) if formhash else '❌',
                    )
                )

            if not loginhash or not formhash:
                # 参数提取失败时，把实际响应打印出来（避免"为什么"的盲目排查）
                self.log('登录失败：无法提取 loginhash/formhash', 'error')
                preview = (last_text or '')[:700].replace('\r', ' ').replace('\n', ' ')
                self.log('  诊断信息：HTTP %d  响应预览（前600字符）：%s' % (last_code, preview[:600]), 'error')
                self.log('  可能原因：① 青龙服务器IP被MT论坛CDN/WAF/防火墙拦截（返回验证页而非登录页）', 'error')
                self.log('            ② 响应头 Content-Encoding 丢失导致乱码（本版已加 magic bytes 兜底）', 'error')
                self.log('            ③ 论坛临时维护/升级，登录 HTML 结构变动', 'error')
                self.last_msg = '登录参数提取失败'
                return False

            # ============================================================
            # 3) 提交登录表单
            # ============================================================
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
            _, text, _ = self.session.post(login_url, data=data, timeout=15,
                                           extra_headers={'Referer': LOGIN_INIT})
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
            _, text, _ = self.session.get(SIGN_PAGE, timeout=15)
            formhash = (self._extract(r'name="formhash"\s+value="([a-f0-9]{8})"', text)
                        or self._extract(r'formhash=([a-f0-9]{8})', text))
            if not formhash:
                if ('请先登录' in text) or ('登录' in text and 'formhash' not in text):
                    self.log('签到失败：未登录或Cookie已过期，尝试重新登录...', 'warning')
                    if self.login():
                        return self.sign_in()
                self.log('签到失败：无法获取 formhash', 'error')
                self.last_msg = '签到失败: formhash 获取失败'
                return False

            sign_url = '%s&formhash=%s&format=text' % (SIGN_API, formhash)
            _, text, _ = self.session.get(sign_url, timeout=15,
                                          extra_headers={'Referer': SIGN_PAGE})
            text = text.strip()

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
#  青龙面板：环境变量读取（兼容多种变量名、多种分隔符）
# ====================================================================
def env(names, default=None):
    if isinstance(names, str):
        names = [names]
    for n in names:
        for key in [n, n.upper(), n.lower()]:
            if key in os.environ and os.environ[key].strip():
                return os.environ[key].strip()
    return default


def env_bool(names, default=False):
    v = env(names)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'y', 'on', '开', '是', '启用')


def env_int(names, default):
    v = env(names)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _split_accounts(raw):
    if not raw:
        return []
    text = raw.replace('\r\n', '\n').replace('\r', '\n').replace('&&', '&').replace('|||', '&')
    for ch in ['\n', ';', '＋', '，']:
        text = text.replace(ch, '&')
    pairs = [p.strip() for p in text.split('&') if p.strip()]
    result = []
    for pair in pairs:
        u, p = None, None
        for sep in ['#', '|', '----', '---', '@@@', ':::', '=',
                    '\t', '＃', '｜', '｜｜', '@@']:
            if sep in pair:
                parts = pair.split(sep, 1)
                if len(parts) == 2:
                    u, p = parts[0].strip(), parts[1].strip()
                    break
        if not (u and p):
            parts = pair.split(None, 1)
            if len(parts) == 2:
                u, p = parts[0].strip(), parts[1].strip()
        if u and p:
            result.append((u, p))
        else:
            _println('⚠️  跳过无效账号条目: %s' % pair, tag='warn')
    return result


def load_accounts_from_env():
    accounts = []

    raw_json = env(['MT_BBS_JSON', 'MTBBS_JSON', 'MT_BBS_ACCOUNTS_JSON'])
    if raw_json:
        try:
            j = json.loads(raw_json)
            if isinstance(j, list):
                for item in j:
                    if isinstance(item, dict):
                        u = str(item.get('username') or item.get('user') or item.get('u') or '').strip()
                        p = str(item.get('password') or item.get('pwd') or item.get('p') or '').strip()
                        if u and p:
                            accounts.append((u, p))
        except Exception as e:
            _println('⚠️  MT_BBS_JSON 解析失败: %s' % e, tag='warn')

    raw_str = env(['MT_BBS_ACCOUNTS', 'MTBBS_ACCOUNTS', 'MT_BBS_COOKIE',
                   'MT_BBS_Accounts', 'MTBBSCK'])
    if raw_str:
        accounts.extend(_split_accounts(raw_str))

    single_u = env(['MT_BBS_USER', 'MTBBS_USER', 'MT_BBS_USERNAME', 'MT_BBS_USR'])
    single_p = env(['MT_BBS_PASSWORD', 'MTBBS_PASSWORD', 'MT_BBS_PWD', 'MT_BBS_PASS'])
    if single_u and single_p:
        accounts.append((single_u, single_p))

    seen, uniq = set(), []
    for u, p in accounts:
        if u not in seen:
            seen.add(u)
            uniq.append((u, p))
    return uniq


# ====================================================================
#  青龙日志输出 + 推送通知
# ====================================================================
_LOG_LINES = []


def _println(msg='', tag=None):
    ts = datetime.now().strftime('%H:%M:%S')
    if tag == 'ok':
        prefix = '✅ '
    elif tag == 'err':
        prefix = '❌ '
    elif tag == 'warn':
        prefix = '⚠️  '
    elif tag == 'info':
        prefix = 'ℹ️  '
    else:
        prefix = ''
    line = '[%s] %s%s' % (ts, prefix, msg)
    print(line, flush=True)
    _LOG_LINES.append('%s%s' % (prefix, msg))


# ---- 青龙通知三级 fallback ----
def _ql_notify_send(title, content):
    # Level 1: 经典 notify.py -> send(title, content)
    try:
        # 把青龙脚本可能存在的所有目录加到 path（兼容各种版本）
        extra_dirs = [
            os.path.dirname(os.path.abspath(__file__)),
            os.getcwd(),
            os.environ.get('QL_SCRIPT_DIR', ''),
            (os.environ.get('QL_DIR', '') + '/data/scripts') if os.environ.get('QL_DIR') else '',
            (os.environ.get('QL_DIR', '') + '/scripts') if os.environ.get('QL_DIR') else '',
            '/ql/data/scripts',
            '/ql/scripts',
            '/jd/scripts',
        ]
        for d in extra_dirs:
            if d and os.path.isdir(d) and d not in sys.path:
                sys.path.insert(0, d)
        from notify import send  # type: ignore
        try:
            send(title, content)
            _println('已通过 notify.py 推送通知', tag='info')
            return True
        except Exception as e1:
            _println('notify.py send 失败: %s，尝试 ql CLI' % e1, tag='warn')
    except Exception:
        pass

    # Level 2: ql notify -t "title" -c "content"  (青龙 3.x CLI)
    ql = shutil.which('ql')
    if ql:
        try:
            r = subprocess.run([ql, 'notify', '-t', title, '-c', content],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                _println('已通过 `ql notify` 推送通知', tag='info')
                return True
            _println('`ql notify` 退出码 %s: %s' % (
                r.returncode, (r.stderr or r.stdout).strip()[:200]), tag='warn')
        except Exception as e2:
            _println('调用 ql notify 异常: %s' % e2, tag='warn')

    # Level 2.5: 裸 notify 命令
    notif = shutil.which('notify')
    if notif:
        try:
            r = subprocess.run([notif, title, content],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                _println('已通过 notify 命令推送通知', tag='info')
                return True
        except Exception as e3:
            _println('调用 notify 命令异常: %s' % e3, tag='warn')

    # Level 3: 回退 —— 青龙日志已经输出了
    _println('⚠️  当前环境未配置/未启用通知渠道，结果已输出到日志', tag='warn')
    return False


def decide_need_notify(total, success, policy):
    policy = (policy or 'fail').strip().lower()
    if policy in ('never', 'no', 'off', '0', '关', '否', '不'):
        return False
    if policy in ('always', 'yes', 'on', '1', '开', '是', '总是'):
        return True
    return success < total


# ====================================================================
# 主流程
# ====================================================================
def main():
    print("""
╔══════════════════════════════════════════════╗
║   MT论坛自动签到 · 青龙面板单文件版           ║
║         %s          ║
╚══════════════════════════════════════════════╝
""" % BASE_URL, flush=True)

    # 1. 账号
    accounts = load_accounts_from_env()
    if not accounts:
        _println('❌  未读取到任何账号！', tag='err')
        _println('请在青龙面板 → 环境变量，设置任一：', tag='info')
        _println('   MT_BBS_ACCOUNTS = 用户名1#密码1 & 用户名2#密码2  （推荐）', tag='info')
        _println('   MT_BBS_USER + MT_BBS_PASSWORD                        （单账号）', tag='info')
        _println('   MT_BBS_JSON      = [{"username":"xx","password":"xx"}]  （JSON）', tag='info')
        return 2

    # 2. 配置
    rand_delay = env_bool(['MT_BBS_RANDOM_DELAY', 'MT_BBS_RANDOM'], default=True)
    d_min = env_int(['MT_BBS_DELAY_MIN', 'MT_BBS_DMIN'], 60)
    d_max = env_int(['MT_BBS_DELAY_MAX', 'MT_BBS_DMAX'], 300)
    if d_min > d_max:
        d_min, d_max = d_max, d_min
    notify_policy = env(['MT_BBS_NOTIFY', 'MT_BBS_NOTIFICATION', 'MT_BBS_PUSH'], default='fail')
    int_min = max(0, env_int(['MT_BBS_INTERVAL_MIN'], 2))
    int_max = max(int_min, env_int(['MT_BBS_INTERVAL_MAX'], 6))

    # 2.1 代理（如果 MT 论坛 CDN/WAF 拦截了青龙服务器 IP，就配代理出口）
    proxy_url = env([
        'MT_BBS_PROXY', 'MTBBS_PROXY', 'MT_BBS_HTTP_PROXY',
        'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    ])
    if proxy_url and '://' not in proxy_url:
        proxy_url = 'http://' + proxy_url  # 裸 host:port 默认 http

    # 2.2 导入已登录 Cookie（WAF 完全拦截、账号密码根本登不进去时最有效的兜底）
    cookie_json = env([
        'MT_BBS_COOKIE_JSON', 'MT_BBS_COOKIE', 'MTBBS_COOKIE_JSON',
        'MT_BBS_COOKIES_JSON',
    ])

    _println('读取到账号 %d 个' % len(accounts), tag='info')
    _println('防风控随机延迟: %s  范围 %s~%s 秒' % (
        '已启用' if rand_delay else '已关闭', d_min, d_max), tag='info')
    _println('账号间执行间隔: %d~%d 秒' % (int_min, int_max), tag='info')
    _println('通知策略: %s' % notify_policy, tag='info')
    if proxy_url:
        # 隐去密码部分再打印
        try:
            _p = urllib.parse.urlparse(proxy_url)
            safe = _p.scheme + '://'
            safe += ('***:***@' if _p.username or _p.password else '')
            safe += (_p.hostname or '') + ((':%d' % _p.port) if _p.port else '')
        except Exception:
            safe = proxy_url[:12] + '***'
        _println('代理出口: %s' % safe, tag='info')
    else:
        _println('代理出口: 未设置（直连）', tag='info')
    if cookie_json:
        _println('Cookie JSON: 已提供（将自动按账号名分桶或全局导入）', tag='info')
    print('─' * 56, flush=True)

    # 3. 逐个执行
    results = []
    for idx, (u, p) in enumerate(accounts):
        if idx > 0:
            gap = random.randint(int_min, int_max)
            _println('休眠 %d 秒后处理下一个账号...' % gap, tag='info')
            time.sleep(gap)
        print('', flush=True)
        _println('—— 账号 %d/%d: %s ——' % (idx + 1, len(accounts), u))

        def _make_logger(username):
            def _cb(msg):
                text = msg[len(username) + 3:] if msg.startswith('[%s] ' % username) else msg
                tag = None
                if any(k in msg for k in ('失败', '异常', '错误')):
                    tag = 'err'
                elif any(k in msg for k in ('成功', '完成签到', '✓')):
                    tag = 'ok'
                elif any(k in msg for k in ('跳过', '警告', '⚠', '延迟')):
                    tag = 'warn'
                _println(text, tag=tag)
            return _cb

        signer = BinMTSigner(u, p, log_callback=_make_logger(u),
                             proxy_url=proxy_url, cookie_json=cookie_json)
        try:
            ok = signer.run(delay_range=(d_min, d_max), random_time=rand_delay)
            detail = signer.last_msg or ('签到成功' if ok else '未知错误')
        except Exception as e:
            ok = False
            detail = '执行异常: %s' % e
            _println(detail, tag='err')
        results.append((u, ok, detail))

    # 4. 汇总
    total = len(results)
    success = sum(1 for _, ok, _ in results if ok)
    failed = total - success
    print('\n' + '═' * 56, flush=True)

    title_prefix = '【MT论坛签到】'
    if failed == 0:
        title = title_prefix + '全部成功 %d/%d ✅' % (success, total)
        _println('🎉 所有账号签到全部完成！%d/%d 成功' % (success, total), tag='ok')
    elif success == 0:
        title = title_prefix + '全部失败 %d/%d ❌' % (success, total)
        _println('💥 所有账号均签到失败！%d/%d 成功' % (success, total), tag='err')
    else:
        title = title_prefix + '部分成功 %d/%d ⚠️' % (success, total)
        _println('📊 签到完成: 成功 %d，失败 %d' % (success, failed), tag='warn')

    detail_lines = []
    for i, (u, ok, msg) in enumerate(results, 1):
        mark = '✅' if ok else '❌'
        line = '%d. %s  %s — %s' % (i, mark, u, msg[:60])
        detail_lines.append(line)
        print('  ' + line, flush=True)
    print('═' * 56, flush=True)

    # 5. 推送通知
    if decide_need_notify(total, success, notify_policy):
        body_lines = _LOG_LINES[-80:]
        body = '\n'.join(body_lines)
        body += '\n\n── 明细汇总 ──\n' + '\n'.join(detail_lines)
        body += '\n\n时间: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body += '\n论坛: %s' % BASE_URL
        try:
            _ql_notify_send(title, body)
        except Exception as e:
            _println('推送通知异常: %s' % e, tag='warn')
    else:
        _println('通知策略为 "%s"，当前结果无需推送。' % notify_policy, tag='info')

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    try:
        code = main()
    except KeyboardInterrupt:
        print('\n用户取消执行。', flush=True)
        code = 130
    except Exception as _e:
        print('\n💥 脚本致命异常: %s' % _e, flush=True)
        import traceback
        traceback.print_exc()
        code = 99
    sys.exit(code)
