"""Live hardware microphone diagnostic tool for BUDDY.

Tests the actual SoundDeviceAudioCapture implementation for 5 seconds
and reports exact hardware metrics, buffer shapes, dtypes, and RMS energy levels.
"""

import asyncio
import math
import struct
import sys
import time
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.core import BuddyConfig
from app.voice import AudioDeviceManager, EnergyVAD, SoundDeviceAudioCapture


async def main() -> None:
    print("=" * 65)
    print(" BUDDY LIVE HARDWARE MICROPHONE DIAGNOSTIC")
    print("=" * 65)

    config = BuddyConfig()
    device_mgr = AudioDeviceManager()
    inputs = device_mgr.list_input_devices()
    print(f"Total Input Devices Found: {len(inputs)}")
    for d in inputs[:5]:
        print(f"  [{d.device_id}] {d.name} ({d.max_input_channels}ch, {d.default_sample_rate:.0f}Hz)")

    capture = SoundDeviceAudioCapture(
        sample_rate=config.audio_sample_rate,
        channels=config.audio_channels,
        chunk_ms=config.voice_audio_chunk_ms,
        max_queue_chunks=config.voice_audio_queue_size,
        persistent=True,
    )

    print("\nCapture Configuration:")
    print(f"  Sample Rate:     {capture.sample_rate} Hz")
    print(f"  Channels:        {capture.channels}")
    print(f"  Chunk Sizing:    {capture._chunk_size} frames ({config.voice_audio_chunk_ms} ms)")
    print(f"  Persistent:      {capture.persistent}")
    print(f"  Queue Capacity:  {config.voice_audio_queue_size} chunks")

    print("\nStarting 5-second live capture test...")
    print(">>> SPEAK INTO YOUR MICROPHONE NOW (or observe room noise) <<<")

    t_start = time.perf_counter()
    await capture.start()

    chunks = []
    rms_values = []
    zero_chunks = 0
    nonzero_chunks = 0
    total_bytes = 0

    end_time = time.monotonic() + 5.0
    while time.monotonic() < end_time:
        try:
            chunk = await capture.read_chunk(timeout=0.1)
            chunks.append(chunk)
            total_bytes += len(chunk)

            # Analyze chunk
            count = len(chunk) // 2
            if count > 0:
                samples = struct.unpack(f"<{count}h", chunk[: count * 2])
                if all(s == 0 for s in samples):
                    zero_chunks += 1
                else:
                    nonzero_chunks += 1
                sum_sq = sum(s * s for s in samples)
                rms = math.sqrt(sum_sq / count)
                rms_values.append(rms)
            else:
                zero_chunks += 1
        except asyncio.TimeoutError:
            pass

    actual_duration = time.perf_counter() - t_start
    audio_data = await capture.stop()
    await capture.close()

    print("\n" + "=" * 65)
    print(" LIVE DIAGNOSTIC RESULTS")
    print("=" * 65)
    print(f"  DEVICE RESOLVED:     Index {capture.resolved_device_index}")
    print(f"  SAMPLE RATE:         {capture.sample_rate} Hz")
    print(f"  CHANNELS:            {capture.channels}")
    print(f"  DTYPE:               int16 (2 bytes/sample)")
    print(f"  BLOCK SIZE:          {capture._chunk_size} frames ({capture._chunk_size * 2} bytes)")
    print(f"  CALLBACK COUNT:      {capture.total_chunks_received}")
    print(f"  WINDOW CHUNKS READ:  {capture.window_chunks_received}")
    print(f"  OVERFLOW COUNT:      {capture.overflow_count}")
    print(f"  STATUS WARNINGS:     {capture.status_warning_count}")
    print(f"  TOTAL BYTES READ:    {total_bytes}")
    print(f"  TOTAL SAMPLES:       {total_bytes // 2}")
    print(f"  CALCULATED DURATION: {(total_bytes // 2) / capture.sample_rate:.2f}s (Clock: {actual_duration:.2f}s)")
    print(f"  NONZERO CHUNKS:      {nonzero_chunks}")
    print(f"  ZERO CHUNKS:         {zero_chunks}")

    if rms_values:
        min_rms = min(rms_values)
        max_rms = max(rms_values)
        avg_rms = sum(rms_values) / len(rms_values)
        print(f"  MIN RMS:             {min_rms:.2f}")
        print(f"  MAX RMS:             {max_rms:.2f}")
        print(f"  AVERAGE RMS:         {avg_rms:.2f}")
    else:
        print("  RMS:                 NO DATA")

    # Diagnostic Classification
    print("\nCLASSIFICATION:")
    if capture.total_chunks_received == 0:
        print("  -> CATEGORY A: Callback never fired (audio input dead or blocked).")
    elif total_bytes == 0:
        print("  -> CATEGORY B: Callback fired with empty buffers.")
    elif nonzero_chunks == 0 and zero_chunks > 0:
        print("  -> CATEGORY C: Callback fired with all-zero buffers (mic hardware muted).")
    elif nonzero_chunks > 0 and max_rms < 10.0:
        print("  -> CATEGORY D: Real audio arriving but extremely low energy (gain/noise floor issue).")
    else:
        print("  -> CATEGORY E: Real audio arriving with good energy (VAD/lifecycle/pipeline issue).")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
