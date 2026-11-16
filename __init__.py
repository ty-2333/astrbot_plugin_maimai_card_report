"""舞萌报卡 AstrBot 插件。

面向舞萌/音游机厅的排队报卡插件：机厅与群号绑定、多机台多方位报卡识别、
排卡人数查询、超时自动清零、异常报卡过滤与黑名单，以及每日开门/闭店语自动生成发送，
并提供完整的 WebUI 控制面板。
"""

import sys

if sys.version_info < (3, 10):
    raise RuntimeError(
        "astrbot_plugin_maimai_card_report 需要 Python 3.10 或更高版本。"
    )