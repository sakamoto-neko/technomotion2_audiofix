; =====================================================================
;  Technomotion 2 (TECHMO.exe) - song select preview audio fix
;  Intel syntax, 32-bit, absolute addresses for the original image
;  (ImageBase 0x400000). Assemble with keystone / NASM ("bits 32")
;  at the addresses shown, or just use apply_preview_fix.py.
; =====================================================================
;
;  BACKGROUND
;  ----------
;  Music streams from the .TMM files into DirectSound buffers
;  (0x50000 bytes each = 128 "chunks" of 2560 bytes, ~29 ms per chunk).
;  The per-frame stream update is sub_441220. It has two modes, picked
;  by the flag at [0xA2A3A8]:
;
;    1 = gameplay (set by sub_441680): keeps ~20 chunks written ahead.
;    0 = song select preview (sub_441940): code at 0x441300.
;
;  The original preview code at 0x441300 did this:
;
;      GetCurrentPosition(buf0, &play, &write)
;      p = play / chunkSize
;      if (p != lastPlayChunk) {
;          lastPlayChunk = p
;          fillChunk = (p + 1) % 128      ; only ONE chunk ahead
;          sub_441030()                   ; read 1 chunk from file & write it
;      }
;
;  That means:
;    * Only ~29 ms of audio is ever queued ahead of the play cursor.
;      Modern Windows (DirectSound emulated on WASAPI) has a write
;      cursor 10-30 ms ahead, plus coarse cursor granularity, so
;      the chunk is often written too late.
;    * If a frame takes longer than one chunk, the play cursor jumps
;      by 2+ chunks but only one gets filled. The skipped chunk replays
;      stale data from the previous lap of the ring buffer.
;  Both of these are heard as crackling and distortion.
;
;  THE FIX
;  -------
;  0x441300 now jumps to a code cave at 0x459800 (zero padding at the end
;  of .text; the section VirtualSize is raised from 0x587ED to 0x59000).
;  The new code keeps LEAD chunks written ahead of the play cursor and
;  catches up on every missed chunk:
;
;      if (!fileOpen) return
;      p = GetCurrentPosition().play / chunkSize
;      if (p == lastPlayChunk) return
;      lastPlayChunk = p
;      N = 2 * chunksPerHalf                     ; 128
;      if ((lastFilled - p) mod N > LEAD)        ; fell behind (long stall)
;          lastFilled = p                        ;   resync just after cursor
;      target = (p + LEAD) mod N
;      while (lastFilled != target) {
;          lastFilled = (lastFilled + 1) mod N
;          fillChunk  = lastFilled
;          sub_441030()                          ; write the chunk
;      }
;
;  [0xA2AF48] is used as "lastFilled". In the original game it was
;  written (the preview start sets it to 0, which matches chunk 0 being
;  prefilled) but never read, so it is safe to reuse.
;
;  Globals used:
;    0xA2AF50  file-open flag            0xA2AC80  ptr -> IDirectSoundBuffer* (buffer 0)
;    0xA2A3B0  chunk size in bytes       0xA2A35C  chunks per half buffer (64)
;    0xA2AF4C  last seen play chunk      0xA2AF48  last filled chunk (new use)
;    0xA2AF44  chunk index for sub_441030 to fill
;
;  Stack/register contract: same as the original block. On entry esi/edi
;  are already saved by sub_441220, and two dwords are reserved at
;  [esp+8] and [esp+0xC]. Every exit jumps to 0x441359
;  (pop edi / pop esi / add esp,8 / ret).
; ---------------------------------------------------------------------

LEAD equ 10                     ; chunks to keep ahead (~29 ms each)

; ---- hook: replaces original bytes at 0x441300..0x441353 -------------
; org 0x441300
        jmp     0x459800        ; E9 FB 84 01 00, rest of the block NOPed
                                ; (0x441354 "call 0x441030" is kept -
                                ;  the gameplay path still jumps there)

; ---- code cave ------------------------------------------------------
; org 0x459800
preview_update:
        cmp     dword ptr [0xA2AF50], 0         ; stream file open?
        je      0x441359
        mov     ecx, dword ptr [0xA2AC80]
        mov     eax, dword ptr [ecx]            ; IDirectSoundBuffer*
        lea     ecx, [esp+0xC]
        push    ecx                             ; &writeCursor
        lea     ecx, [esp+0xC]
        push    ecx                             ; &playCursor
        push    eax                             ; this
        mov     edx, dword ptr [eax]
        call    dword ptr [edx+0x10]            ; GetCurrentPosition
        mov     eax, dword ptr [esp+8]          ; playCursor
        xor     edx, edx
        div     dword ptr [0xA2A3B0]            ; eax = play chunk p
        cmp     eax, dword ptr [0xA2AF4C]
        je      0x441359                        ; cursor still in same chunk
        mov     dword ptr [0xA2AF4C], eax
        mov     esi, dword ptr [0xA2A35C]
        add     esi, esi                        ; esi = N (ring size in chunks)
        mov     edi, eax                        ; edi = p

        ; distance = (lastFilled - p) mod N ; resync if we fell behind
        mov     eax, dword ptr [0xA2AF48]
        sub     eax, edi
        add     eax, esi
        xor     edx, edx
        div     esi
        cmp     edx, LEAD
        jbe     .ahead_ok
        mov     dword ptr [0xA2AF48], edi
.ahead_ok:
        ; target = (p + LEAD) mod N
        lea     eax, [edi+LEAD]
        xor     edx, edx
        div     esi
        mov     edi, edx

.fill_loop:
        mov     eax, dword ptr [0xA2AF48]
        cmp     eax, edi
        je      0x441359                        ; caught up -> return
        inc     eax
        xor     edx, edx
        div     esi                             ; edx = (lastFilled+1) mod N
        mov     dword ptr [0xA2AF48], edx
        mov     dword ptr [0xA2AF44], edx       ; chunk to fill
        call    0x441030                        ; read file chunk -> buffer(s)
        jmp     .fill_loop
