#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int wmain(int argc, wchar_t** argv) {
    if (argc != 5) return 2;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    HMODULE module = LoadLibraryW(argv[1]);
    if (!module) return 3;
    auto install = reinterpret_cast<BOOL (*)(const wchar_t*, const wchar_t*)>(GetProcAddress(module, "DdmInstall"));
    auto dumps = reinterpret_cast<void (*)(BOOL)>(GetProcAddress(module, "DdmSetDumpEnabled"));
    if (!install || !dumps || !install(argv[2], argv[3])) return 4;
    dumps(argv[4][0] == L'1');
    if (argv[4][0] == L'n') return 23;
    RaiseException(0xc0000005, EXCEPTION_NONCONTINUABLE, 0, nullptr);
    return 99;
}
