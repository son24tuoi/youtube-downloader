// Launcher: chạy python\pythonw.exe app\app.py nằm cạnh file exe này
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
    wchar_t dir[MAX_PATH], py[MAX_PATH], script[MAX_PATH], line[3 * MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    swprintf(py, MAX_PATH, L"%ls\\python\\pythonw.exe", dir);
    swprintf(script, MAX_PATH, L"%ls\\app\\app.py", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Thiếu thư mục 'python' hoặc 'app' bên cạnh file exe.\n"
                          L"Hãy giải nén đầy đủ file zip rồi chạy lại.",
                    L"YouTube Downloader", MB_ICONERROR);
        return 1;
    }
    swprintf(line, 3 * MAX_PATH, L"\"%ls\" \"%ls\"", py, script);
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(py, line, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Không khởi động được Python đi kèm.", L"YouTube Downloader", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
