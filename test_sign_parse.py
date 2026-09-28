# -*- coding: utf-8 -*-
"""TDD 测试: MT论坛签到响应解析逻辑 Bug

Bug 现象:
    第一次点击签到 → 论坛实际签到成功，但脚本显示签到失败(False)
    第二次点击签到 → 显示今日已签(True)

根因:
    1. format=empty&inajax=1 返回 Discuz inajax 回调格式，不是 <root> XML
    2. 成功关键词集合过于狭窄，漏掉"恭喜""奖励""积分""金币""+XX"等常见成功提示
"""

import os
import sys
import re
import unittest

# 把脚本所在目录加进 path，方便导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 核心签到逻辑已移到 mt_sign_core.py（GUI版 mt_sign.py 只含 Tk 界面，青龙版 mt_sign_qinglong.py 是命令行壳）
import mt_sign_core as mt_sign


# ---- 模拟 k_misign 常见的签到响应文本 ----
# 注意: 这些是 Discuz! k_misign 插件真实返回的各种格式变体

FIRST_SIGN_SUCCESS_GET_TEXT = (
    # GET + format=text  → 标准 <root><![CDATA[]]></root> 格式
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<root><![CDATA[恭喜您获得 12 个金币,签到奖励!]]></root>'
)

FIRST_SIGN_SUCCESS_NO_KEYWORD = (
    # 成功但不包含 "签到成功" 或 "获得"  （会被旧逻辑误判为失败）
    '<root><![CDATA[恭喜您签到奖励 8 积分 + 连续签到3天]]></root>'
)

FIRST_SIGN_SUCCESS_INAJAX = (
    # POST + format=empty&inajax=1  → Discuz inajax 回调 (最常见的"第一次失败"元凶)
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<root><![CDATA[succeedhandle_k_misignsign("恭喜您！今日签到奖励：10 金币","","")]]></root>'
)

FIRST_SIGN_SUCCESS_PURE_CALLBACK = (
    # 极端情况: inajax 直接返回 succeedhandle 回调函数 无 <root>
    'succeedhandle_k_misignsign("签到完成 +15 金币感谢支持", \'succeed\', \'\')'
)

FIRST_SIGN_SUCCESS_PLUS_ONLY = (
    # 返回只有 "+10 金币"  没有"成功""获得"等字样
    '<root><![CDATA[+10 金币 明天继续签到吧]]></root>'
)

FIRST_SIGN_SUCCESS_CONGRATS = (
    '<root><![CDATA[恭喜签到成功，获得每日签到奖励：金币 × 5]]></root>'
)

REPEAT_SIGN = (
    # 第二天(或第二次点击):论坛已经签过 → 返回"今日已签"
    '<root><![CDATA[今日已签，请明天再来！您的签到奖励已领取完毕]]></root>'
)

REPEAT_SIGN_CHONG_FU = (
    '<root><![CDATA[您今天已经签到过了，请勿重复签到]]></root>'
)

NEED_LOGIN = (
    '<root><![CDATA[请先登录后再进行签到操作]]></root>'
)

ERROR_MESSAGE = (
    # 真正的签到失败
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<root><![CDATA[errorhandle_k_misignsign("签到功能暂时关闭","","")]]></root>'
)

EMPTY_BUT_ACTUALLY_SUCCEED = (
    # inajax 返回空 CDATA 但签到实际成功（边界情况）
    '<root><![CDATA[]]></root>'
)


def _old_parse_result(text):
    """模拟 现有 sign_in() 里的 解析逻辑（有bug）"""
    msg_m = re.search(r'<root>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</root>', text, re.S)
    msg = msg_m.group(1) if msg_m else text
    if '今日已签' in msg or '重复签到' in msg:
        return True
    if '签到成功' in msg or '获得' in msg:
        return True
    if '登录' in msg or 'login' in msg.lower():
        return False
    if msg:
        return ('成功' in msg) or ('获得' in msg)
    return False


def _new_parse_result(text):
    """使用 BinMTSigner 类中新的静态方法解析"""
    return mt_sign.BinMTSigner._parse_sign_result(text)


class TestSignResultBug(unittest.TestCase):
    """先证明旧逻辑在第一次签到成功时返回 False (BUG复现)"""

    # ========== 第一部分: 用现有逻辑复现 BUG  (RED 阶段) ==========
    def test_old_parse_fails_on_first_sign_inajax(self):
        """inajax 回调格式 -> 旧逻辑误判为 False (BUG复现)"""
        result = _old_parse_result(FIRST_SIGN_SUCCESS_INAJAX)
        # 我们"期望它失败"，证明bug存在 —— 实际上应该是 True，但旧逻辑返回 False
        self.assertFalse(result, '旧逻辑应当无法识别 inajax 成功回调 → bug被复现')

    def test_old_parse_fails_on_reward_no_keyword(self):
        """恭喜签到奖励 X 积分 → 旧逻辑漏判(BUG)"""
        result = _old_parse_result(FIRST_SIGN_SUCCESS_NO_KEYWORD)
        self.assertFalse(result, '旧逻辑应当漏判"恭喜签到奖励积分" → bug被复现')

    def test_old_parse_fails_on_pure_plus(self):
        """+10金币 → 旧逻辑漏判"""
        result = _old_parse_result(FIRST_SIGN_SUCCESS_PLUS_ONLY)
        self.assertFalse(result, '旧逻辑应当漏判"+10金币" → bug被复现')

    def test_old_parse_fails_on_pure_callback(self):
        """无 <root> 纯 succeedhandle 回调 → 旧逻辑漏判"""
        result = _old_parse_result(FIRST_SIGN_SUCCESS_PURE_CALLBACK)
        self.assertFalse(result, '旧逻辑应当漏判纯 succeedhandle → bug被复现')

    def test_old_parse_ok_on_repeat(self):
        """重复签到 —— 旧逻辑判断正确(True)"""
        self.assertTrue(_old_parse_result(REPEAT_SIGN), '重复签到应当识别')
        self.assertTrue(_old_parse_result(REPEAT_SIGN_CHONG_FU))

    def test_old_parse_ok_on_login_needed(self):
        """需要登录 —— 旧逻辑判断正确(False)"""
        self.assertFalse(_old_parse_result(NEED_LOGIN))

    # ========== 第二部分: 用新逻辑通过所有成功案例 ==========
    def test_new_parse_first_sign_inajax_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_INAJAX))

    def test_new_parse_first_sign_get_text_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_GET_TEXT))

    def test_new_parse_reward_no_keyword_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_NO_KEYWORD))

    def test_new_parse_pure_callback_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_PURE_CALLBACK))

    def test_new_parse_plus_only_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_PLUS_ONLY))

    def test_new_parse_congrats_success(self):
        self.assertTrue(_new_parse_result(FIRST_SIGN_SUCCESS_CONGRATS))

    def test_new_parse_repeat_still_true(self):
        self.assertTrue(_new_parse_result(REPEAT_SIGN))
        self.assertTrue(_new_parse_result(REPEAT_SIGN_CHONG_FU))

    def test_new_parse_login_still_false(self):
        self.assertFalse(_new_parse_result(NEED_LOGIN))

    def test_new_parse_error_still_false(self):
        self.assertFalse(_new_parse_result(ERROR_MESSAGE))


if __name__ == '__main__':
    unittest.main(verbosity=2)
