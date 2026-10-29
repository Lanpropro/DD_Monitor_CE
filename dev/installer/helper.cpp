// Native folder picker and a named entry point for the Inno uninstaller.
#include <windows.h>
#include <shlobj.h>
#include <shellapi.h>
#include <string>

static int PickFolder(HWND owner, const wchar_t* initial, const wchar_t* output) {
    HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(initialized)) return 2;
    IFileOpenDialog* dialog = nullptr;
    HRESULT result = CoCreateInstance(CLSID_FileOpenDialog, nullptr,
        CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog));
    if (SUCCEEDED(result)) {
        result = dialog->SetOptions(FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM |
            FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR | FOS_DONTADDTORECENT);
        dialog->SetTitle(L"选择 DD监控室CE 的安装位置");
        dialog->SetOkButtonLabel(L"选择文件夹");
        IShellItem* folder = nullptr;
        if (SUCCEEDED(SHCreateItemFromParsingName(initial, nullptr, IID_PPV_ARGS(&folder)))) {
            dialog->SetFolder(folder);
            folder->Release();
        }
        if (SUCCEEDED(result)) result = dialog->Show(owner);
        IShellItem* selected = nullptr;
        if (SUCCEEDED(result)) result = dialog->GetResult(&selected);
        if (selected) {
            PWSTR path = nullptr;
            result = selected->GetDisplayName(SIGDN_FILESYSPATH, &path);
            if (SUCCEEDED(result)) {
                HANDLE file = CreateFileW(output, GENERIC_WRITE, 0, nullptr,
                    CREATE_ALWAYS, FILE_ATTRIBUTE_TEMPORARY, nullptr);
                if (file == INVALID_HANDLE_VALUE) result = HRESULT_FROM_WIN32(GetLastError());
                else {
                    DWORD written = 0;
                    int bytes = WideCharToMultiByte(CP_UTF8, 0, path, -1, nullptr, 0, nullptr, nullptr);
                    std::string utf8(bytes, '\0');
                    WideCharToMultiByte(CP_UTF8, 0, path, -1, &utf8[0], bytes, nullptr, nullptr);
                    --bytes; // Do not include the terminating NUL in the text file.
                    if (!WriteFile(file, utf8.data(), bytes, &written, nullptr) || written != bytes)
                        result = E_FAIL;
                    CloseHandle(file);
                }
                CoTaskMemFree(path);
            }
            selected->Release();
        }
        dialog->Release();
    }
    CoUninitialize();
    if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) return 1;
    return SUCCEEDED(result) ? 0 : 2;
}

static int LaunchUninstaller(const wchar_t* arguments) {
    wchar_t module[32768];
    DWORD length = GetModuleFileNameW(nullptr, module, ARRAYSIZE(module));
    if (!length || length == ARRAYSIZE(module)) return 2;
    std::wstring directory(module, length);
    directory.resize(directory.find_last_of(L"\\/") + 1);
    directory += L".ddm-uninstall\\";
    WIN32_FIND_DATAW found;
    HANDLE search = FindFirstFileW((directory + L"unins*.exe").c_str(), &found);
    std::wstring target;
    unsigned count = 0;
    if (search != INVALID_HANDLE_VALUE) {
        do {
            if ((found.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0) {
                target = directory + found.cFileName;
                ++count;
            }
        } while (FindNextFileW(search, &found));
        FindClose(search);
    }
    if (count == 1) {
        SHELLEXECUTEINFOW info = { sizeof(info) };
        info.lpFile = target.c_str();
        info.lpParameters = arguments;
        info.lpDirectory = directory.c_str();
        info.nShow = SW_SHOWNORMAL;
        if (ShellExecuteExW(&info)) return 0;
    }
    MessageBoxW(nullptr, L"未找到唯一的卸载程序。请从 Windows 设置中的“已安装的应用”卸载 DD监控室CE。",
        L"DD监控室CE 卸载", MB_OK | MB_ICONERROR);
    return 2;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) {
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32);
    int count = 0;
    LPWSTR* values = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!values) return 2;
    int result;
    if (count >= 2 && wcscmp(values[1], L"--pick-folder") == 0) {
        result = 2;
        if (count == 5) {
            HWND owner = reinterpret_cast<HWND>(_wcstoui64(values[4], nullptr, 10));
            result = PickFolder(owner, values[2], values[3]);
        }
    } else result = LaunchUninstaller(arguments);
    LocalFree(values);
    return result;
}
