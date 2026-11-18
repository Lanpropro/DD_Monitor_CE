"""Additional cache categories in the common cache usage card."""
from . import cache_cleanup, theme
from .cache_settings import CacheUsagePanel


ITEMS = (
    ('emoticons', '弹幕表情', '清理磁盘中的表情图片；再次出现时下载。已显示的表情可能仍在内存中。'),
    ('sc-avatars', 'SC 头像', '清理醒目留言头像；再次需要时下载，不影响关注列表头像。'),
    ('banners', '直播间横幅', '清理空间横幅和房间背景图片；再次加载时下载，离线时可能暂缺背景。'),
    ('plugin-catalog', '插件商店目录', '清理商店列表和更新记录缓存；刷新商店后重建，不卸载插件。离线列表将暂不可用。'),
    ('web-login', '网页登录 HTTP 缓存', '安排在下次打开网页登录时清理；不自动打开登录页，不清除 Cookie、账号或登录资料。'),
    ('logs', '历史日志与崩溃转储', '仅清理今天以前且未占用的本体记录。保留当前日志和进行中的诊断；清理后无法追溯对应的旧问题。'),
)
LABELS = {kind: title for kind, title, _hint in ITEMS}


def cache_colors():
    return dict(zip(LABELS, (theme.ACCENT, theme.PINK, theme.SUCCESS, theme.WARNING, '#8176d9', theme.TEXT3)))


class ExtraCachePanel(CacheUsagePanel):
    def __init__(self, parent=None, *, root=None):
        super().__init__('其他缓存与历史日志', parent, root=root, backend=cache_cleanup,
                         labels=LABELS, colors=cache_colors, deferred=('web-login',),
                         details={kind: hint for kind, _title, hint in ITEMS},
                         hint='点击扇区或勾选类别。网页登录缓存会在下次打开登录时清理，日志仅统计今天以前的本体记录。')
