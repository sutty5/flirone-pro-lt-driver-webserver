# FLIR One Pro LT Driver Internals

This document details the low-level implementation of the custom C driver (`driver/flirone.c`) and the reverse-engineered USB protocol used by the FLIR One Pro LT (Gen 3).

## Hardware Specifications

- **Vendor ID**: `0x09CB`
- **Product ID**: `0x1996`
- **USB Class**: Vendor Specific
- **Interfaces**:
  - `0`: Control/Status
  - `1`: File I/O
  - `2`: Video Stream

## 5. Visible Stream Quirk (Partial Writes & Padding)

The visible camera stream outputs standard JPEG frames. However, high-speed streaming over V4L2loopback can sometimes lead to "partial writes," where the OS buffer is full and only writes a fragment of the frame. Standard `write()` calls often return `EAGAIN` or a partial byte count, which naive drivers ignore, leading to dropped frame tails and visual tearing ("overread" errors).

**Symptom:** Visual tearing, green bands at the bottom of the image, or "mjpeg: overread 8" errors in the logs.

**Fix:** 
1.  **Robust Write Loop**: The driver logic was updated to loop on `write()` until the entire buffer is sent to the V4L2 device, handling `EAGAIN` and partial success.
2.  **Safety Padding**: We append **64KB** of zero-padding to every JPEG. This acts as a safety buffer for decoders that might speculatively read past the End Of Image (EOI) marker.

## 6. Radiometric Calibration Strategy

The FLIR One Pro LT does not expose standard linear 14-bit data like the older Lepton 2.5; it outputs a 16-bit signal that requires specific Planck conversion.

**Problem:** Default Lepton 3.5 constants (`PlanckO = -7340`) produce erroneous readings (>1000°C) for this sensor's raw range (~3000-4000).

**Solution (Gain-Based Model):**
We use a verified "synthetic calibration" profile in `camera_config.json`:
*   **PlanckO (Offset) = 0**: Set to zero to prevent negative overflow in logarithmic calculations.
*   **PlanckR1 (Gain) = 500,000**: empirically derived gain to map the observed ~3500 raw counts to ~25°C-30°C (Room Temp).
*   **Formula**: `T = B / log(R1 / (raw - O) + F) - 273.15`

This configuration ensures stable, positive-domain temperature readings without requiring the extraction of proprietary factory OTP memory.

## Initialization Sequence

The camera requires a specific sequence of Control Transfers to wake up and start streaming. Failing to send these exact packets often puts the device into a non-responsive state requiring a physical re-plug.

### 1. Configuration
The driver sets the USB device configuration to `3`. This exposes the necessary endpoints.

### 2. Magic "Start" Sequence
The function `start_streaming()` sends vendor-specific commands via `libusb_control_transfer`:

1.  **Stop Interface 2**: `Request 0x0B, Value 0, Index 2`
2.  **Stop Interface 1**: `Request 0x0B, Value 0, Index 1`
3.  **Start Interface 1**: `Request 0x0B, Value 1, Index 1`
4.  **Start Video (EP 0x85)**: `Request 0x0B, Value 1, Index 2`

*Note: These commands likely correspond to internal firmware states (e.g., "Stop Frame Interface", "Start FileIO", "Start Buffer Fill").*

## Protocol & Data Format

The camera streams data via **Bulk Endpoint 0x85**.

### Frame Structure
Data is received in raw chunks. The driver buffers these chunks until it detects a valid frame header.

*   **Magic Header**: `EF BE 00 00` (Little Endian)
*   **Header Size**: 28 bytes
*   **Packet Layout**:

| Offset | Size | Description |
| t --- | t --- | t --- |
| 0 | 4 | Magic Bytes (`EF BE 00 00`) |
| 4 | 4 | Sequence / Type |
| 8 | 4 | **Frame Size** (Total bytes following header) |
| 12 | 4 | **Thermal Size** (Bytes of thermal data) |
| 16 | 4 | **JPEG Size** (Bytes of visible data) |
| 20 | 8 | Reserved / Timestamp |

### Thermal Data (16-bit Raw)
*   **Resolution**: 80 x 60
*   **Format**: Little Endian 16-bit unsigned integers (`uint16`).
*   **Data Layout in Buffer**:
    The thermal data is interleaved in a specific way that requires offset correction.
    - **Top half (lines 0-29)**: Data starts at `LINE_OFFSET` within each stride.
    - **Bottom half (lines 30-59)**: Data starts at `LINE_OFFSET + 4` bytes.
    - *The driver transparently handles this de-interleaving.*
*   **Output**: Written to `/dev/video10` as `V4L2_PIX_FMT_Y16`.

### Visible Data (MJPEG)
*   **Resolution**: 640 x 480
*   **Format**: Standard MJPEG stream.
*   **Overread Protection**: The driver appends 65,536 bytes (64KB) of zero-padding to every JPEG frame written to `/dev/video11`. This prevents visual tearing caused by decoders (like OpenCV) reading past the end of the buffer when optimizing logic.

## Stability Mechanisms

### 1. Disconnect Recovery
The driver implements a "Retry & Wait" loop during initialization (`init_usb`). If the device is not found immediately (e.g., during re-enumeration after a crash), the driver polls for 5 seconds.

### 2. Validated Writes
Code checks for `FF D8` (Start of Image) markers before writing visible frames to avoid piping garbage data to the video loopback device.

## V4L2 Loopback Integration
The driver opens two V4L2 devices for output. These are **automatically discovered** by label (`FLIR_Thermal`, `FLIR_Visible`) at startup, but can be manually pinned in `start.sh`.

1.  **Thermal**: Defaults to auto-discovery (e.g. `/dev/video10`). Configured for 16-bit support.
2.  **Visible**: Defaults to auto-discovery (e.g. `/dev/video11`). Configured for MJPEG.

### Atomic Writes & Pass-Through
To eliminate visual tearing ("overread" errors) caused by the V4L2 loopback buffer handling:
1.  **Atomic Writes**: The driver attempts to write the entire JPEG frame to `/dev/video11` in a single system call. If the write would block or is partial, the frame is **dropped** rather than sent as a torn fragment.
2.  **Web Viewer Pass-Through**: The web viewer (`web_viewer.py`) bypasses OpenCV decoding for the visible stream. It reads raw MJPEG frames directly from the loopback device using `os.read()`, ensuring zero-latency and 100% frame integrity.
