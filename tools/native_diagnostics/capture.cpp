// Production crash evidence. The faulting process only signals a prestarted helper.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dbghelp.h>
#include <cstdio>
#include <string>

struct Shared {
    DWORD pid, tid, code;
    volatile LONG dumps;
    ULONG64 exceptionPointers;
    CONTEXT context;
};

#ifndef DDM_WATCHER
static Shared* shared;
static HANDLE mapping, requested, completed, watcher;
static LPTOP_LEVEL_EXCEPTION_FILTER previous;
static volatile LONG handling;

static LONG WINAPI capture(EXCEPTION_POINTERS* exception) {
    if (InterlockedCompareExchange(&handling, 1, 0) == 0 && shared) {
        shared->tid = GetCurrentThreadId();
        shared->code = exception->ExceptionRecord->ExceptionCode;
        shared->exceptionPointers = reinterpret_cast<ULONG64>(exception);
        shared->context = *exception->ContextRecord;
        SetEvent(requested);
        HANDLE handles[] = {completed, watcher};
        WaitForMultipleObjects(2, handles, FALSE, 8000);
    }
    return previous ? previous(exception) : EXCEPTION_CONTINUE_SEARCH;
}

extern "C" __declspec(dllexport) void DdmSetDumpEnabled(BOOL enabled) {
    if (shared) InterlockedExchange(&shared->dumps, enabled ? 1 : 0);
}

extern "C" __declspec(dllexport) BOOL DdmInstall(const wchar_t* helper, const wchar_t* directory) {
    if (shared) return TRUE;
    wchar_t prefix[120];
    swprintf_s(prefix, L"Local\\DDMonitorCE-crash-%lu-%llu", GetCurrentProcessId(), GetTickCount64());
    std::wstring name(prefix);
    mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, sizeof(Shared), (name + L"-map").c_str());
    requested = CreateEventW(nullptr, FALSE, FALSE, (name + L"-request").c_str());
    completed = CreateEventW(nullptr, FALSE, FALSE, (name + L"-done").c_str());
    if (!mapping || !requested || !completed) return FALSE;
    shared = static_cast<Shared*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared)));
    if (!shared) return FALSE;
    shared->pid = GetCurrentProcessId();
    std::wstring command = L"\"" + std::wstring(helper) + L"\" \"" + name + L"\" \"" + directory + L"\"";
    STARTUPINFOW startup = {sizeof(startup)};
    PROCESS_INFORMATION process = {};
    if (!CreateProcessW(helper, &command[0], nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                        nullptr, nullptr, &startup, &process)) {
        UnmapViewOfFile(shared); shared = nullptr;
        return FALSE;
    }
    CloseHandle(process.hThread);
    watcher = process.hProcess;
    HANDLE handles[] = {completed, watcher};
    if (WaitForMultipleObjects(2, handles, FALSE, 5000) != WAIT_OBJECT_0) {
        SetEvent(requested); // No exception: helper exits rather than becoming an orphan.
        UnmapViewOfFile(shared); shared = nullptr;
        return FALSE;
    }
    previous = SetUnhandledExceptionFilter(capture);
    return TRUE;
}
#else
static void frame(FILE* output, HANDLE process, ULONG64 address, bool comma) {
    IMAGEHLP_MODULEW64 module = {sizeof(module)};
    if (SymGetModuleInfoW64(process, address, &module)) {
        char name[256] = {};
        WideCharToMultiByte(CP_UTF8, 0, module.ModuleName, -1, name, sizeof(name), nullptr, nullptr);
        // ModuleName is the basename, never a user's full filesystem path.
        fprintf(output, "%s{\"module\":\"%s\",\"offset\":\"0x%llx\"}",
                comma ? "," : "", name, address - module.BaseOfImage);
    } else {
        fprintf(output, "%s{\"address\":\"0x%llx\"}", comma ? "," : "", address);
    }
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 3) return 2;
    std::wstring name(argv[1]);
    HANDLE mapping = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, (name + L"-map").c_str());
    HANDLE requested = OpenEventW(SYNCHRONIZE, FALSE, (name + L"-request").c_str());
    HANDLE completed = OpenEventW(EVENT_MODIFY_STATE, FALSE, (name + L"-done").c_str());
    if (!mapping || !requested || !completed) return 3;
    auto shared = static_cast<Shared*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Shared)));
    if (!shared) return 4;
    HANDLE process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | SYNCHRONIZE, FALSE, shared->pid);
    if (!process) return 5;
    SetEvent(completed); // Ready; no polling while the application is healthy.
    HANDLE handles[] = {requested, process};
    if (WaitForMultipleObjects(2, handles, FALSE, INFINITE) != WAIT_OBJECT_0 || !shared->tid) return 0;
    wchar_t stem[100];
    FILETIME now; GetSystemTimeAsFileTime(&now);
    swprintf_s(stem, L"\\native-crash-%lu-%08lx%08lx", shared->pid, now.dwHighDateTime, now.dwLowDateTime);
    std::wstring path = std::wstring(argv[2]) + stem;
    DWORD dumpError = 0;
    bool dumpSaved = false;
    if (shared->dumps) {
        HANDLE file = CreateFileW((path + L".dmp.part").c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file != INVALID_HANDLE_VALUE) {
            MINIDUMP_EXCEPTION_INFORMATION info = {shared->tid,
                reinterpret_cast<EXCEPTION_POINTERS*>(shared->exceptionPointers), TRUE};
            dumpSaved = MiniDumpWriteDump(process, shared->pid, file,
                static_cast<MINIDUMP_TYPE>(MiniDumpNormal | MiniDumpWithThreadInfo | MiniDumpWithUnloadedModules),
                &info, nullptr, nullptr) != FALSE;
            if (!dumpSaved) dumpError = GetLastError();
            CloseHandle(file);
            if (dumpSaved) MoveFileW((path + L".dmp.part").c_str(), (path + L".dmp").c_str());
            else DeleteFileW((path + L".dmp.part").c_str());
        } else dumpError = GetLastError();
    }
    FILE* output = nullptr;
    _wfopen_s(&output, (path + L".json.part").c_str(), L"wb");
    if (output) {
        fprintf(output, "{\"schema\":1,\"pid\":%lu,\"tid\":%lu,\"exception_code\":\"0x%08lx\",\"dump_requested\":%s,\"dump_saved\":%s,\"dump_error\":%lu,",
                shared->pid, shared->tid, shared->code, shared->dumps ? "true" : "false", dumpSaved ? "true" : "false", dumpError);
        SymSetOptions(SYMOPT_DEFERRED_LOADS | SYMOPT_FAIL_CRITICAL_ERRORS | SYMOPT_NO_PROMPTS);
        BOOL symbols = SymInitialize(process, "", TRUE); // No symbol server/network lookup.
        fprintf(output, "\"stack_error\":%lu,\"frames\":[", symbols ? 0 : GetLastError());
        CONTEXT context = shared->context;
        STACKFRAME64 stack = {};
        stack.AddrPC = {context.Rip, 0, AddrModeFlat};
        stack.AddrFrame = {context.Rbp, 0, AddrModeFlat};
        stack.AddrStack = {context.Rsp, 0, AddrModeFlat};
        HANDLE thread = OpenThread(THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, shared->tid);
        frame(output, process, context.Rip, false);
        ULONG64 last = context.Rip;
        for (int count = 1; symbols && thread && count < 64; ++count) {
            if (!StackWalk64(IMAGE_FILE_MACHINE_AMD64, process, thread, &stack, &context, nullptr,
                             SymFunctionTableAccess64, SymGetModuleBase64, nullptr) || !stack.AddrPC.Offset) break;
            if (stack.AddrPC.Offset == last && count == 1) continue;
            frame(output, process, stack.AddrPC.Offset, true);
            last = stack.AddrPC.Offset;
        }
        fprintf(output, "]}\n");
        fclose(output);
        MoveFileW((path + L".json.part").c_str(), (path + L".json").c_str());
        if (thread) CloseHandle(thread);
        if (symbols) SymCleanup(process);
    }
    SetEvent(completed);
    return 0;
}
#endif
