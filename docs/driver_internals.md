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
*   **Overread Protection**: The driver appends 128 bytes of zero-padding to every JPEG frame written to `/dev/video11`. This prevents visual tearing caused by decoders (like OpenCV) reading past the end of the buffer when optimizing logic.

## Stability Mechanisms

### 1. Disconnect Recovery
The driver implements a "Retry & Wait" loop during initialization (`init_usb`). If the device is not found immediately (e.g., during re-enumeration after a crash), the driver polls for 5 seconds.

### 2. Validated Writes
Code checks for `FF D8` (Start of Image) markers before writing visible frames to avoid piping garbage data to the video loopback device.

## V4L2 Loopback Integration
The driver opens two file descriptors for output:
1.  **Thermal**: `/dev/video10` (Configured with `bytesperline = width * 2` for 16-bit support).
2.  **Visible**: `/dev/video11` (Configured as MJPEG).
