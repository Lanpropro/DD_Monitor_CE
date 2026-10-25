"""在线插件目录生成与本体发布脚本的更新元数据。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev.tools.build_plugin_catalog import build
from ddm import online, version


def main():
    assert version.VERSION == '0.5.2'
    notes = (Path(__file__).resolve().parents[1] / f'docs/releases/RELEASE-{version.VERSION_TAG}.md').read_text(encoding='utf-8')
    assert notes.strip(), 'Current Release Markdown must exist; its wording is editable after publication'
    technical = (Path(__file__).resolve().parents[1] / 'docs/online-updates.md').read_text(encoding='utf-8')
    for feature in ('legacy-program-backup-', 'SHA-256', '不自动删除恢复备份', 'DDM_SETTINGS_PROCESS=0'):
        assert feature in technical, feature
    notes = (Path(__file__).resolve().parents[1] / 'docs/releases/RELEASE-v0.5.md').read_text(encoding='utf-8')
    assert notes.startswith('# DD监控室CE v0.5 更新说明')
    for feature in ('通知中心', '音量控制', '500ms', '画面黑屏', '只有弹幕', '关注栏完好', 'DD监控室CE.exe'):
        assert feature in notes, feature
    for feature in ('正式版本 v0.4 到 v0.5', '播放内核从 VLC 更换为 libmpv',
                    '全局和单窗口编解码设置', 'NVIDIA NVENC', '弹幕绘制增加 Qt Quick',
                    '合并连续窗口尺寸更新', '独立 WASAPI 音频输出', '切换 B 站编码前后台探测',
                    'AV1 直存选择 MOV／TS', '全屏残留选中边框', '恢复布局后背景透明异常'):
        assert feature in notes, feature
    assert '0.4（未发布）' not in notes
    notes = (Path(__file__).resolve().parents[1] / 'docs/releases/RELEASE-v0.4.md').read_text(encoding='utf-8')
    assert '[Milkyway-66](https://github.com/Milkyway-66)' in notes
    assert 'https://github.com/Lanpropro/DD_Monitor_CE/pull/6' in notes
    assert 'https://github.com/Lanpropro/DD_Monitor_CE/pull/7' in notes
    assert '[Soraray](https://github.com/Soraray)' in notes
    assert '维护者修改后的版本' in notes

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
        with patch.object(online, 'latest_manifest', return_value=data), \
                patch.object(online, 'releases', return_value=[]):
            offers = online.plugin_catalog(None, '0.3')
            assert not offers[0]['available'] and '0.4' in offers[0]['reason']
            assert online.plugin_catalog(None, '0.4')[0]['available']
    source = (Path(__file__).resolve().parents[1] / 'dev/build_release.ps1').read_text(encoding='utf-8')
    assert 'ddm-build.json' in source and 'app-update.json' in source and 'Get-FileHash' in source
    assert 'update_protocol = 1' in source and "platform = 'windows-x64'" in source
    assert '--version-file $versionInfo' in source and 'build_windows_version.py' in source
    assert 'archive --format=zip --output=$snapshot HEAD' in source
    for pattern in ('plugins_user/*', 'utils/*', 'videos/*', 'dev/*promo*'):
        assert pattern in source
    assert 'Get-ChildItem (Join-Path $repo "plugins_user")' not in source
    assert 'Get-ChildItem (Join-Path $repo "utils")' not in source
    assert 'diff --quiet HEAD -- ddm blivedm assets main.py requirements.txt' in source
    assert 'PySide6==6.11.2' in source and '$qtVersion -ne "6.11.2"' in source
    assert r'$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$(Split-Path -Parent $py)"' in source
    assert r'$env:PATH = $previousBuildPath' in source
    # Exercise the source export filter, including an added runtime module.
    export = source.split("$extractSource = @'\n", 1)[1].split("\n'@", 1)[0]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        archive = root / 'snapshot.zip'
        files = {'main.py': b'entry', 'ddm/new_feature.py': b'feature',
                 'utils/config.json': b'private', 'plugins_user/local/data.bin': b'private',
                 'videos/private.mp4': b'private'}
        with zipfile.ZipFile(archive, 'w') as package:
            for name, data in files.items():
                package.writestr(name, data)
        with patch.object(sys, 'argv', ['export', str(archive), str(root / 'out')]):
            exec(compile(export, 'release-source-export', 'exec'), {})
        assert (root / 'out/ddm/new_feature.py').read_bytes() == b'feature'
        assert (root / 'out/main.py').read_bytes() == b'entry'
        assert not (root / 'out/utils').exists()
        assert not (root / 'out/plugins_user').exists()
        assert not (root / 'out/videos').exists()
    assert 'user_notice_accepted = $true' in source
    assert 'if ($version -eq "v0.3.1")' in source
    assert '$exeDir = Join-Path $OutDir $display' in source
    assert '--onedir --name $display' in source
    assert 'UTF8Encoding($false)' in source
    assert 'Remove-Item -LiteralPath $testConfig -Force' in source
    assert '$remoteExeName = "DDMonitorCE-$version-exe.zip"' in source
    assert 'asset_name = $remoteExeName' in source
    assert 'notes = [string]$updateNotes' in source
    # 实际解析 PowerShell，防止只验证字符串而漏掉脚本语法。
    import subprocess
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        "$tokens = $null; $errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
        "(Join-Path (Get-Location) 'dev/build_release.ps1'), [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    # The EXE must use the same default rendering path as the accepted run.cmd.
    import os
    import runpy
    hook = Path(__file__).resolve().parents[1] / 'dev/pyi_rth_pyside6_paths.py'
    for explicit, expected in ((None, '1'), ('0', '0'), ('1', '1')):
        with patch.dict(os.environ, {'DDM_PYI_DEBUG': '0'}), \
                patch.object(sys, 'frozen', True, create=True):
            os.environ.pop('DDM_QTQUICK_DANMAKU', None)
            if explicit is not None:
                os.environ['DDM_QTQUICK_DANMAKU'] = explicit
            runpy.run_path(str(hook))
            assert os.environ['DDM_QTQUICK_DANMAKU'] == expected
    for explicit, expected in ((None, '1'), ('0', '0'), ('1', '1')):
        with patch.dict(os.environ, {'DDM_PYI_DEBUG': '0'}), \
                patch.object(sys, 'frozen', True, create=True):
            os.environ.pop('DDM_SETTINGS_PROCESS', None)
            if explicit is not None:
                os.environ['DDM_SETTINGS_PROCESS'] = explicit
            runpy.run_path(str(hook))
            assert os.environ['DDM_SETTINGS_PROCESS'] == expected
    print('PASS: plugin catalog generation, compatibility, current version and parsed release update metadata')


if __name__ == '__main__':
    main()
