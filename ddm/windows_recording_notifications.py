"""Windows Notification Center delivery for streamer monitoring events."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring


APP_ID = 'DDMonitorCE.StreamerMonitor'
PROTOCOL = 'ddmonitor-ce-notify'
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='windows-notifications')

# Set the two shell-link identity properties documented by Microsoft. A stub
# CLSID keeps protocol-activated notifications in Notification Center.
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DDM_RECORDING_TOAST)) | ConvertFrom-Json
$programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
$link = Join-Path $programs $data.shortcut
$properties = New-Object -ComObject WScript.Shell
$shortcut = $properties.CreateShortcut($link)
$handler = 'HKCU:\Software\Classes\' + $data.protocol
$command = '"{0}" {1}' -f $data.target, $data.arguments
if (!(Test-Path "$handler\shell\open\command") -or (Get-Item "$handler\shell\open\command").GetValue('') -ne $command) {
    New-Item "$handler\shell\open\command" -Force | Out-Null
    Set-Item $handler ('URL:' + $data.shortcut)
    New-ItemProperty $handler -Name 'URL Protocol' -Value '' -Force | Out-Null
    Set-Item "$handler\shell\open\command" $command
}
if (!(Test-Path $link) -or $shortcut.TargetPath -ne $data.target -or $shortcut.Arguments -ne $data.arguments) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class DdmToastShortcut {
    [StructLayout(LayoutKind.Sequential, Pack=4)]
    struct Key {
        public Guid Format;
        public uint Id;
    }
    [StructLayout(LayoutKind.Explicit, Size=24)]
    struct Value {
        [FieldOffset(0)] public ushort Type;
        [FieldOffset(8)] public IntPtr Pointer;
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface Store {
        void GetCount(out uint count);
        void GetAt(uint index, out Key key);
        void GetValue(ref Key key, out Value value);
        void SetValue(ref Key key, ref Value value);
        void Commit();
    }
    public static void Register(string path, string appId) {
        object link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
        IntPtr text = Marshal.StringToCoTaskMemUni(appId);
        IntPtr guid = Marshal.AllocCoTaskMem(Marshal.SizeOf(typeof(Guid)));
        try {
            IPersistFile file = (IPersistFile)link;
            file.Load(path, 2);
            Store store = (Store)link;
            Key key = new Key { Format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), Id = 5 };
            Value value = new Value { Type = 31, Pointer = text };
            store.SetValue(ref key, ref value);
            Guid activator = new Guid("D8D09A91-E88A-4843-B335-B6CF9B8B0B02");
            Marshal.StructureToPtr(activator, guid, false);
            key.Id = 26;
            value = new Value { Type = 72, Pointer = guid };
            store.SetValue(ref key, ref value);
            store.Commit();
            file.Save(path, true);
        } finally {
            Marshal.FreeCoTaskMem(text);
            Marshal.FreeCoTaskMem(guid);
            Marshal.FinalReleaseComObject(link);
        }
    }
}
'@
    $tempLink = Join-Path $programs ([Guid]::NewGuid().ToString() + '.lnk')
    try {
        $newShortcut = $properties.CreateShortcut($tempLink)
        $newShortcut.TargetPath = $data.target
        $newShortcut.Arguments = $data.arguments
        $newShortcut.WorkingDirectory = $data.working
        $newShortcut.Save()
        [DdmToastShortcut]::Register($tempLink, $data.appId)
        Move-Item -LiteralPath $tempLink -Destination $link -Force
    } finally {
        if (Test-Path -LiteralPath $tempLink) { Remove-Item -LiteralPath $tempLink }
    }
}
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
$null = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]
$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]::new()
$xml.LoadXml($data.xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$toast.Tag = $data.tag
$toast.SuppressPopup = $data.suppressPopup
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($data.appId).Show($toast)
"""


def toast_xml(title, message):
    toast = Element('toast', activationType='protocol', launch=PROTOCOL + ':')
    binding = SubElement(SubElement(toast, 'visual'), 'binding', template='ToastGeneric')
    SubElement(binding, 'text').text = title
    SubElement(binding, 'text').text = message
    return tostring(toast, encoding='unicode')


def _send(title, message, *, tag=None, suppress_popup=False):
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    executable = Path(sys.executable)
    root = Path(__file__).resolve().parents[1]
    if getattr(sys, 'frozen', False):
        target, arguments, working = executable, '', executable.parent
    else:
        # Match run.cmd's local Qt dependency path when a notification launches
        # the development checkout directly through its Python interpreter.
        launcher = ("import runpy,sys; from pathlib import Path; main=Path(sys.argv[1]); "
                    "deps=main.parent/'work'/'deps'; "
                    "sys.path[:0]=[str(deps)] if (deps/'PySide6'/'QtCore.pyd').is_file() else []; "
                    "sys.argv=[str(main)]; runpy.run_path(str(main),run_name='__main__')")
        windowless = executable.with_name('pythonw.exe')
        target = windowless if windowless.is_file() else executable
        arguments = subprocess.list2cmdline(['-c', launcher, str(root / 'main.py')])
        working = root
    data = dict(xml=toast_xml(title, message), tag=tag or uuid4().hex[:16], suppressPopup=suppress_popup,
                appId=APP_ID, protocol=PROTOCOL,
                shortcut='DD监控室CE 主播监控.lnk', target=str(target), arguments=arguments, working=str(working))
    env = dict(os.environ, DDM_RECORDING_TOAST=b64encode(json.dumps(data).encode('utf-8')).decode('ascii'))
    program = system / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    command = b64encode(_SCRIPT.encode('utf-16-le')).decode('ascii')
    try:
        subprocess.run([str(program), '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
                       env=env, capture_output=True, check=True, timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, 'stderr', b'') or type(error).__name__.encode('ascii')
        print('[Windows 通知] ' + detail.decode('utf-8', errors='replace').strip(), file=sys.stderr)


def send_recording_notification(title, message, *, tag=None, suppress_popup=False):
    if sys.platform == 'win32':
        _worker.submit(_send, title, message, tag=tag, suppress_popup=suppress_popup)
