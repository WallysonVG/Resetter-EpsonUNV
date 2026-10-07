"""
Acesso à impressora pela USB no Windows, SEM trocar o driver.

O Windows expõe toda impressora USB através do driver "usbprint.sys".
Ele cria uma "interface de dispositivo" que dá para abrir com CreateFile
e conversar com ReadFile/WriteFile, nos dois sentidos. É o mesmo caminho
que os programas da própria Epson usam, então a impressão continua normal.

Só usa a biblioteca padrão do Python (ctypes).
"""
import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    raise ImportError("usb_windows só funciona no Windows")

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


# {28d78fad-5a12-11d1-ae5b-0000f803a8c2} = GUID_DEVINTERFACE_USBPRINT
GUID_USBPRINT = GUID(0x28D78FAD, 0x5A12, 0x11D1,
                     (ctypes.c_ubyte * 8)(0xAE, 0x5B, 0x00, 0x00, 0xF8, 0x03, 0xA8, 0xC2))


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), wintypes.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                  wintypes.LPCWSTR]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIo.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]


def listar_impressoras_usb():
    """Devolve os caminhos de todas as impressoras USB conectadas."""
    caminhos = []
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(GUID_USBPRINT), None, None,
                                      DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if h == INVALID_HANDLE_VALUE:
        return caminhos
    try:
        i = 0
        while True:
            dados = SP_DEVICE_INTERFACE_DATA()
            dados.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(GUID_USBPRINT),
                                                        i, ctypes.byref(dados)):
                break
            necessario = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(dados), None, 0,
                                                      ctypes.byref(necessario), None)
            buf = ctypes.create_string_buffer(necessario.value)
            # cbSize da estrutura de detalhe: 8 no Python 64 bits, 6 no 32 bits
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(dados), buf,
                                                         necessario, None, None):
                caminhos.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
            i += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return caminhos


class UsbPrintIO:
    """Abre a impressora e oferece read()/write() com tempo limite."""

    def __init__(self, caminho, timeout_ms=1500):
        self.caminho = caminho
        self.timeout_ms = timeout_ms
        self.h = None

    def __enter__(self):
        self.h = kernel32.CreateFileW(self.caminho, GENERIC_READ | GENERIC_WRITE,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                      OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if self.h == INVALID_HANDLE_VALUE or not self.h:
            erro = ctypes.get_last_error()
            raise OSError(f"Não consegui abrir a impressora (erro {erro}). "
                          "Feche o Epson Status Monitor e qualquer impressão em andamento.")
        self.evento = kernel32.CreateEventW(None, True, False, None)
        return self

    def __exit__(self, *exc):
        if self.h:
            kernel32.CloseHandle(self.evento)
            kernel32.CloseHandle(self.h)
            self.h = None

    def _io(self, func, buf, tamanho):
        ov = OVERLAPPED()
        ov.hEvent = self.evento
        kernel32.ResetEvent(self.evento)
        feito = wintypes.DWORD(0)
        ok = func(self.h, buf, tamanho, None, ctypes.byref(ov))
        if not ok:
            erro = ctypes.get_last_error()
            if erro != ERROR_IO_PENDING:
                raise OSError(f"Falha de E/S na USB (erro {erro})")
            if kernel32.WaitForSingleObject(self.evento, self.timeout_ms) != WAIT_OBJECT_0:
                kernel32.CancelIo(self.h)
                kernel32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(feito), True)
                return 0
        kernel32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(feito), True)
        return feito.value

    def write(self, dados):
        buf = ctypes.create_string_buffer(bytes(dados), len(dados))
        n = self._io(kernel32.WriteFile, buf, len(dados))
        if n != len(dados):
            raise OSError(f"Escrita incompleta na USB ({n} de {len(dados)} bytes)")
        return n

    def read(self, tamanho=512):
        buf = ctypes.create_string_buffer(tamanho)
        n = self._io(kernel32.ReadFile, buf, tamanho)
        return buf.raw[:n]
