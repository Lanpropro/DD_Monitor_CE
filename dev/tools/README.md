# 资源与发布辅助工具

从仓库根目录执行：

| 工具 | 用途 |
| --- | --- |
| [build_brand_assets.py](build_brand_assets.py) | 从已跟踪的 SVG 品牌源生成 PNG 和 ICO；会写入项目资源 |
| [build_plugin_catalog.py](build_plugin_catalog.py) | 从指定插件 ZIP 的清单生成发布目录，不执行插件代码 |

```powershell
python dev/tools/build_brand_assets.py
python dev/tools/build_plugin_catalog.py --tag v1.1 --output plugin-catalog.json domestic_live-1.1.zip global_live-1.1.zip
```

生成工具按需运行，不由默认测试入口执行。对应回归是 `dev/selfcheck_brand_assets.py` 和 `dev/selfcheck_release_metadata.py`。
