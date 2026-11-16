// Windows check-process diagnostics only; never link into the application.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dbghelp.h>
#include <cstdio>
#include <cstring>

static LONG recording = 0;

static void write_line(const char* text)
{
    DWORD written;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), text, static_cast<DWORD>(strlen(text)),
              &written, nullptr);
}

static void write_frame(DWORD64 address)
{
    char path[MAX_PATH] = "unknown", text[2048];
    HMODULE module = nullptr;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                      GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                      reinterpret_cast<LPCSTR>(address), &module);
    if (module)
        GetModuleFileNameA(module, path, MAX_PATH);
    alignas(SYMBOL_INFO) char storage[sizeof(SYMBOL_INFO) + MAX_SYM_NAME] = {};
    auto symbol = reinterpret_cast<SYMBOL_INFO*>(storage);
    symbol->SizeOfStruct = sizeof(SYMBOL_INFO);
    symbol->MaxNameLen = MAX_SYM_NAME;
    DWORD64 displacement = 0;
    const BOOL resolved = SymFromAddr(GetCurrentProcess(), address, &displacement, symbol);
    snprintf(text, sizeof(text), "  %s+0x%llx %s+0x%llx\n", path,
             address - reinterpret_cast<DWORD64>(module),
             resolved ? symbol->Name : "?", displacement);
    write_line(text);
}

static LONG CALLBACK capture(EXCEPTION_POINTERS* exception)
{
    if (exception->ExceptionRecord->ExceptionCode != EXCEPTION_ACCESS_VIOLATION ||
        InterlockedCompareExchange(&recording, 1, 0))
        return EXCEPTION_CONTINUE_SEARCH;
    char text[256];
    snprintf(text, sizeof(text), "NATIVE_ACCESS_VIOLATION tid=%lu operation=%llu address=0x%llx\n",
             GetCurrentThreadId(), exception->ExceptionRecord->ExceptionInformation[0],
             exception->ExceptionRecord->ExceptionInformation[1]);
    write_line(text);
    CONTEXT context = *exception->ContextRecord;
    STACKFRAME64 stack = {};
    stack.AddrPC.Offset = context.Rip;
    stack.AddrStack.Offset = context.Rsp;
    stack.AddrFrame.Offset = context.Rbp;
    stack.AddrPC.Mode = stack.AddrStack.Mode = stack.AddrFrame.Mode = AddrModeFlat;
    write_frame(context.Rip);
    // One capture per process also serializes DbgHelp calls after initialization.
    for (int i = 0; i < 60; ++i) {
        if (!StackWalk64(IMAGE_FILE_MACHINE_AMD64, GetCurrentProcess(), GetCurrentThread(),
                         &stack, &context, nullptr, SymFunctionTableAccess64,
                         SymGetModuleBase64, nullptr) || !stack.AddrPC.Offset)
            break;
        write_frame(stack.AddrPC.Offset);
    }
    // Keep faulthandler and the original failure/exit code intact.
    return EXCEPTION_CONTINUE_SEARCH;
}

extern "C" __declspec(dllexport) int install()
{
    SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS);
    if (!SymInitialize(GetCurrentProcess(), nullptr, TRUE))
        return 0;
    return AddVectoredExceptionHandler(1, capture) != nullptr;
}
