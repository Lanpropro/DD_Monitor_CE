"""首次启动的用户须知与一次性显示状态。"""
from . import config
from .notice_dialog import NoticeDialog
from .version import DISPLAY_NAME


NOTICE_HTML = """
<h3>1. 开源与免费</h3>
<p>本软件是一款免费、开源的软件，源码公开于：
<a href="https://github.com/Lanpropro/DD_Monitor_CE">项目仓库</a>，遵循
<a href="https://github.com/Lanpropro/DD_Monitor_CE/blob/main/LICENSE">GNU LGPL 2.1 开源许可证</a>。</p>
<p>本项目不收取软件下载或使用费用，也没有付费解锁功能。如果你通过付费渠道获得本软件，请认准官方项目地址。</p>
<h3>2. 官方获取渠道</h3>
<p>请通过以下渠道下载软件及获取更新：
<a href="https://github.com/Lanpropro/DD_Monitor_CE/releases">官方发布页面</a>。</p>
<p>第三方修改、重新打包的版本可能与官方版本存在差异。</p>
<h3>3. 第三方平台与插件</h3>
<p>本软件是独立的开源项目，与所支持的直播平台不存在官方合作或隶属关系。</p>
<p>部分功能需要登录第三方平台或安装插件。请自行决定是否使用，并留意插件来源和所需权限。</p>
<h3>4. 使用与反馈</h3>
<p>请遵守所使用平台的相关规则，尊重主播及其他权利人的权益。</p>
<p>本项目由<a href="https://space.bilibili.com/193559518">我个人</a>维护。
遇到问题或希望提出建议，请通过
<a href="https://github.com/Lanpropro/DD_Monitor_CE/issues">提交 Issues</a>或者
<a href="https://space.bilibili.com/193559518">B站私信</a>联系我。</p>
"""


class UserNoticeDialog(NoticeDialog):
    DEFAULT_HEIGHT = 620

    def __init__(self, parent=None, *, settings=None):
        super().__init__("用户须知", f"欢迎使用 {DISPLAY_NAME}", "我已阅读并确认",
                         parent, settings=settings)
        self.content.setHtml(NOTICE_HTML)


def confirm_user_notice(state: dict) -> bool:
    if state.get("user_notice_accepted"):
        return True
    dialog = UserNoticeDialog(settings=state.get("settings"))
    try:
        dialog.exec()
        # 沿用原配置键，确认或直接关闭都记为已显示。
        state["user_notice_accepted"] = True
        state.setdefault("version", config.STATE_VERSION)
        config.save(state)
        return True
    finally:
        dialog.deleteLater()
