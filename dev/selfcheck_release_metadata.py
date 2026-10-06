"""在线插件目录生成与本体发布脚本的更新元数据。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_plugin_catalog import build
from ddm import online, version


def main():
    assert version.VERSION == '0.3'
    with tempfile.TemporaryDirectory(prefix='ddm-catalog-test-') as temporary:
        archive = Path(temporary) / 'global_live-1.2.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('global_live/plugin.json', json.dumps({
                'id': 'global_live', 'name': '海外直播', 'description': 'test', 'version': '1.2',
                'min_app_version': '0.4'}))
            package.writestr('global_live/plugin.py', "raise RuntimeError('must not execute')")
        data = build([archive], 'v1.2')
        entry = data['plugins'][0]
        assert entry['min_app_version'] == '0.4'
        assert entry['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
        assert entry['size'] == archive.stat().st_size
        with patch.object(online, 'latest_manifest', return_value=data):
            offers = online.plugin_catalog(None, '0.3')
            assert not offers[0]['available'] and '0.4' in offers[0]['reason']
            assert online.plugin_catalog(None, '0.4')[0]['available']
    source = (Path(__file__).resolve().parents[1] / 'dev/build_release.ps1').read_text(encoding='utf-8')
    assert 'ddm-build.json' in source and 'app-update.json' in source and 'Get-FileHash' in source
    assert 'update_protocol = 1' in source and "platform = 'windows-x64'" in source
    # 实际解析 PowerShell，防止只验证字符串而漏掉脚本语法。
    import subprocess
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        "$tokens = $null; $errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
        "(Join-Path (Get-Location) 'dev/build_release.ps1'), [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    print('PASS: plugin catalog generation, compatibility, 0.3 version and parsed release update metadata')


if __name__ == '__main__':
    main()
