"""Reserve memory for Sierra and keep offline work below normal priority."""
import ctypes
import os

RESERVE_BYTES=4*1024**3


def available_memory():
    if os.name!='nt':return None
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
            ['total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','extended']]
    status=MemoryStatus();status.length=ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):return None
    return int(status.available_physical)


def ensure_memory(reserve=None,reclaim=False):
    if reserve is None:reserve=RESERVE_BYTES
    available=available_memory()
    if available is not None and available<reserve and reclaim and os.name=='nt':
        # Release only this worker's resident cache pages; never touch Sierra
        # or other processes. Memory-mapped data remains backed by its files.
        kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
        empty=ctypes.windll.psapi.EmptyWorkingSet;empty.argtypes=[ctypes.c_void_p]
        empty(kernel.GetCurrentProcess())
        available=available_memory()
    if available is not None and available<reserve:
        raise MemoryError(f'Ricerca arrestata per preservare Sierra: RAM libera {available/1024**3:.2f} GiB, riserva minima {reserve/1024**3:.0f} GiB. Chiudi altre elaborazioni o riprova con un periodo minore.')


def lower_priority():
    if os.name=='nt':
        kernel=ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        kernel.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x4000) # BELOW_NORMAL_PRIORITY_CLASS


def initialize_research(reserve_gib=4):
    global RESERVE_BYTES
    if not isinstance(reserve_gib,(int,float)) or not 2<=reserve_gib<=8:
        raise ValueError('Riserva RAM: 2..8 GiB')
    RESERVE_BYTES=int(reserve_gib*1024**3)
    lower_priority();ensure_memory()
