# Preview Audio Fix for TechnoMotion: The 2nd Dance Floor

A small binary patch for **Technomotion 2** (`TECHMO.exe`). It fixes the crackly, distorted song preview audio on the music select screen on modern Windows.

Gameplay audio, demo mode and the `.TMM` song files are not changed.

## The problem

On the music select screen, the preview of the highlighted song crackles badly on current versions of Windows, while the same song plays cleanly in gameplay.

## Cause

Songs stream from the `.TMM` files into DirectSound ring buffers. Each buffer is `0x50000` bytes, split into 128 chunks of 2560 bytes (about 29 ms each). Once per frame, the game checks the play position and refills chunks.

- **Gameplay** keeps about 20 chunks (roughly 0.5 s) queued ahead of playback.
- **The song select preview** queues only **one** chunk (about 29 ms) ahead. It also refills only one chunk per frame, and only when the play position has moved into a new chunk.

That worked on early-2000s sound hardware. On modern Windows, DirectSound runs as an emulation layer on top of WASAPI, which adds 10–30 ms of write latency and reports the play position in coarse steps. The next chunk is often written too late. When a frame takes longer than one chunk, the play position skips a chunk that never gets refilled, so old audio from the previous pass through the buffer plays instead. The result is crackling and distortion.

## The fix

The preview update code at `0x441300` is replaced with a jump to new code placed in unused padding at the end of `.text` (`0x459800`). The new code:

1. keeps **LEAD** chunks (default 10, about 290 ms) written ahead of the play position
2. fills **every** chunk the play position has passed since the last frame, not just one
3. restarts just ahead of the play position if a long stall (such as loading) leaves it too far behind

The full annotated source and pseudocode are in [`preview_fix.asm`](preview_fix.asm).

## Files

| File | Description |
|---|---|
| `apply_preview_fix.py` | Patcher script. Needs Python 3 only, with no extra packages. |
| `preview_fix.asm` | Annotated assembly source for the patch. Kept as documentation; the patcher contains the assembled bytes. |

## Requirements

- Python 3.6 or newer ([python.org](https://www.python.org/downloads/))
- An **unmodified** `TECHMO.exe` (471,040 bytes). The script checks the exact bytes it replaces and refuses to touch any other version.

## Usage

The script can be run from any folder.

### Easiest: patch in place

Copy `apply_preview_fix.py` into the game folder (the one that contains `TECHMO.exe`) and run it:

```
python apply_preview_fix.py
```

On Windows you can also double-click the script if Python is set to open `.py` files, or use `py apply_preview_fix.py`.

With no arguments, the script looks for `TECHMO.exe` in the current folder first, then in the folder where the script itself is.

### Patch a game folder from anywhere

```
python apply_preview_fix.py "F:\Technomotion 2\Game"
python apply_preview_fix.py "F:\Technomotion 2\Game\TECHMO.exe"
```

When patching in place:

- If `TECHMO.exe` is unpatched, it is first backed up as **`TECHMO_original.exe`** in the same folder. An existing backup is never overwritten.
- If `TECHMO.exe` is already patched and `TECHMO_original.exe` exists, it is patched again from the backup. Use this to change `--lead`.

### Write the patched exe to a new file

```
python apply_preview_fix.py TECHMO_original.exe TECHMO_patched.exe
```

The source file is left unchanged. It must be the unmodified exe.

### Options

| Option | Description |
|---|---|
| `--lead N` | Chunks kept queued ahead of playback, from 2 to 100 (default `10`, about 290 ms). Raise it if you still hear occasional crackles. A higher value adds a little preview latency but does not affect gameplay. |
| `-h`, `--help` | Show usage. |

Example:

```
python apply_preview_fix.py --lead 16
```

## Undo

Copy `TECHMO_original.exe` back over `TECHMO.exe`.

## Compatibility notes

- `TechnoMotionLoader.exe` still works. It changes only one byte at `0x440357`, which this patch does not touch.
- Works with dgVoodoo 2 (the bundled `DDraw.dll` / `D3D*.dll`).
- One game variable, `0xA2AF48`, is reused as the "last filled chunk" index. The original code writes it but never reads it.

## Technical reference

| Address | Purpose |
|---|---|
| `0x441940` | Starts the preview: opens the `.TMM` file, seeks to the preview start, fills chunk 0 and starts playback |
| `0x441220` | Per-frame stream update. `[0xA2A3A8]` selects gameplay mode (1) or preview mode (0) |
| `0x441300` | Original preview-mode refill block, **replaced with `jmp 0x459800`** |
| `0x441030` | Reads one chunk from the file into the chunk index in `[0xA2AF44]` |
| `0x459800` | New refill code (code cave) |
| `0xA2A3B0` | Chunk size in bytes (2560) |
| `0xA2A35C` | Chunks per half buffer (64) |
| `0xA2AF4C` | Last seen play chunk |
| `0xA2AF50` | Stream file open flag |

In the `.text` section header, the virtual size is raised from `0x587ED` to `0x59000` so that the cave lies inside the section.

## Disclaimer

This is an unofficial fan patch. Technomotion 2 and all related assets belong to their respective owners. Do not distribute game files with this patch; share only the patcher and source.
