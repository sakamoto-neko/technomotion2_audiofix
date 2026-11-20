#!/usr/bin/env python3
"""
Technomotion 2 - song select preview audio fix (TECHMO.exe patcher)

Usage:
    python apply_preview_fix.py [GAME_FOLDER | TECHMO.exe] [--lead N]
    python apply_preview_fix.py SRC.exe DST.exe [--lead N]

With no path, the script looks for TECHMO.exe in the current folder and
then in the folder the script is in. With a folder or exe path, it patches
that TECHMO.exe in place:
  * an unpatched TECHMO.exe is first backed up as TECHMO_original.exe
  * if TECHMO.exe is already patched and TECHMO_original.exe exists, it is
    re-patched from the backup (use this to change --lead)
With two paths, SRC (an unmodified exe) is patched and written to DST.

Applies the fix described in preview_fix.asm. Needs only Python 3, no
third-party modules. The bytes being replaced are checked first, so a
different or unexpected exe is never modified.

--lead N   chunks kept written ahead of the play cursor during the preview
           (default 10; each chunk is ~29 ms; must be 2..100).
"""
import argparse, os, shutil, struct, sys

IMAGE_BASE  = 0x400000
TEXT_RVA    = 0x1000        # .text: RVA 0x1000, raw offset 0x1000
TEXT_RAW    = 0x1000

def va2off(va):
    return va - IMAGE_BASE - TEXT_RVA + TEXT_RAW

HOOK_VA     = 0x441300      # start of original preview-update block
HOOK_LEN    = 0x54          # 0x441300..0x441353 (0x441354 'call 0x441030' kept)
CAVE_VA     = 0x459800      # zero padding at end of .text

# Hook: jmp 0x459800, then NOP padding
HOOK = bytes.fromhex("e9fb840100").ljust(HOOK_LEN, b"\x90")

# Cave code assembled from preview_fix.asm at 0x459800 (LEAD = 10).
CAVE = bytes.fromhex(
    "833d50afa20000"        # cmp  dword [0xA2AF50], 0
    "0f844c7bfeff"          # je   0x441359
    "8b0d80aca200"          # mov  ecx, [0xA2AC80]
    "8b01"                  # mov  eax, [ecx]
    "8d4c240c" "51"         # lea  ecx,[esp+0xC] ; push ecx
    "8d4c240c" "51"         # lea  ecx,[esp+0xC] ; push ecx
    "50"                    # push eax
    "8b10" "ff5210"         # mov edx,[eax] ; call [edx+0x10]  GetCurrentPosition
    "8b442408"              # mov  eax, [esp+8]   play cursor
    "31d2" "f735b0a3a200"   # xor edx,edx ; div dword [0xA2A3B0]
    "3b054cafa200"          # cmp  eax, [0xA2AF4C]
    "0f841c7bfeff"          # je   0x441359
    "a34cafa200"            # mov  [0xA2AF4C], eax
    "8b355ca3a200" "01f6"   # mov esi,[0xA2A35C] ; add esi,esi
    "89c7"                  # mov  edi, eax
    "a148afa200"            # mov  eax, [0xA2AF48]
    "29f8" "01f0"           # sub eax,edi ; add eax,esi
    "31d2" "f7f6"           # xor edx,edx ; div esi
    "83fa0a"                # cmp  edx, LEAD          <- LEAD byte (+0x5B)
    "7606"                  # jbe  .ahead_ok
    "893d48afa200"          # mov  [0xA2AF48], edi
    "8d470a"                # lea  eax, [edi+LEAD]    <- LEAD byte (+0x66)
    "31d2" "f7f6" "89d7"    # xor edx,edx ; div esi ; mov edi,edx
    "a148afa200"            # .fill_loop: mov eax,[0xA2AF48]
    "39f8"                  # cmp  eax, edi
    "0f84df7afeff"          # je   0x441359
    "40" "31d2" "f7f6"      # inc eax ; xor edx,edx ; div esi
    "891548afa200"          # mov  [0xA2AF48], edx
    "891544afa200"          # mov  [0xA2AF44], edx
    "e8a077feff"            # call 0x441030
    "ebdb"                  # jmp  .fill_loop
)
LEAD_OFFSETS = (0x5B, 0x66)

# First bytes of the original block (sanity check), and the kept call.
ORIG_HOOK_START = bytes.fromhex("a150afa20085c074508b0d80aca200")
ORIG_KEPT_CALL  = bytes.fromhex("e8d7fcffff")


class PatchError(Exception):
    pass


def patch_bytes(data, lead):
    """Return a patched copy of an unmodified TECHMO.exe image."""
    d = bytearray(data)
    h, c = va2off(HOOK_VA), va2off(CAVE_VA)
    if len(d) < c + len(CAVE) + 16:
        raise PatchError("File is too small to be TECHMO.exe.")
    if d[h:h + HOOK_LEN] == HOOK:
        raise PatchError("ALREADY_PATCHED")
    if d[h:h + len(ORIG_HOOK_START)] != ORIG_HOOK_START \
       or d[h + HOOK_LEN:h + HOOK_LEN + 5] != ORIG_KEPT_CALL:
        raise PatchError("Unexpected bytes at 0x441300 - not the expected TECHMO.exe version.")
    if any(d[c:c + len(CAVE) + 16]):
        raise PatchError("Code cave at 0x459800 is not empty.")

    cave = bytearray(CAVE)
    for o in LEAD_OFFSETS:
        cave[o] = lead
    d[h:h + HOOK_LEN] = HOOK
    d[c:c + len(cave)] = cave

    # Raise .text VirtualSize to 0x59000 so the cave lies inside the section.
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    opt_size = struct.unpack_from("<H", d, pe + 20)[0]
    sec0 = pe + 24 + opt_size
    struct.pack_into("<I", d, sec0 + 8, 0x59000)
    return bytes(d)


def is_patched(path):
    with open(path, "rb") as f:
        f.seek(va2off(HOOK_VA))
        return f.read(HOOK_LEN) == HOOK


def find_exe(arg):
    """Resolve the target TECHMO.exe from an optional folder/exe argument."""
    if arg:
        p = os.path.abspath(arg)
        if os.path.isdir(p):
            p = os.path.join(p, "TECHMO.exe")
        if not os.path.isfile(p):
            raise PatchError(f"Not found: {p}")
        return p
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (os.getcwd(), here):
        p = os.path.join(folder, "TECHMO.exe")
        if os.path.isfile(p):
            return p
    raise PatchError("TECHMO.exe not found in the current folder or the script's "
                     "folder. Pass the game folder or the exe path as an argument.")


def run(args):
    if len(args.paths) == 2:                        # explicit SRC DST
        src, dst = (os.path.abspath(p) for p in args.paths)
        if not os.path.isfile(src):
            raise PatchError(f"Not found: {src}")
        with open(src, "rb") as f:
            data = f.read()
        try:
            out = patch_bytes(data, args.lead)
        except PatchError as e:
            if str(e) == "ALREADY_PATCHED":
                raise PatchError(f"{src} is already patched - use the original exe.")
            raise
        with open(dst, "wb") as f:
            f.write(out)
        print(f"Patched {src}\n     -> {dst}")
    else:                                           # in-place on TECHMO.exe
        exe = find_exe(args.paths[0] if args.paths else None)
        backup = os.path.join(os.path.dirname(exe), "TECHMO_original.exe")
        if is_patched(exe):
            if not os.path.isfile(backup):
                raise PatchError(f"{exe} is already patched and no TECHMO_original.exe "
                                 "backup was found next to it.")
            source = backup
            print(f"{exe} is already patched; re-patching from {backup}")
        else:
            source = exe
        with open(source, "rb") as f:
            out = patch_bytes(f.read(), args.lead)  # validate before touching files
        if source == exe and not os.path.isfile(backup):
            shutil.copy2(exe, backup)
            print(f"Backup: {backup}")
        with open(exe, "wb") as f:
            f.write(out)
        print(f"Patched {exe}")
    print(f"Lead = {args.lead} chunks (~{args.lead * 29} ms)")


def main():
    ap = argparse.ArgumentParser(
        description="Fix crackly song select preview audio in Technomotion 2 (TECHMO.exe).")
    ap.add_argument("paths", nargs="*", metavar="PATH",
                    help="game folder or TECHMO.exe (patched in place), "
                         "or SRC.exe DST.exe; default: look for TECHMO.exe")
    ap.add_argument("--lead", type=int, default=10,
                    help="chunks kept queued ahead of playback, 2-100 (default 10)")
    a = ap.parse_args()
    if len(a.paths) > 2:
        ap.error("give at most two paths")
    if not 2 <= a.lead <= 100:
        ap.error("--lead must be between 2 and 100")
    try:
        run(a)
    except (PatchError, OSError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
