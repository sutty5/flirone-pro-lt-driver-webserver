# flirone-pro-lt-linux

A robust, reverse-engineered driver for the **FLIR One Pro LT** thermal camera on Linux.  
This project unlocks the full potential of your device by outputting **16-bit Raw Radiometric Data** and providing modern visualization tools for both Desktop and Web.

## Features

- **Stable C Driver**: Reverse-engineered USB driver built on `libusb-1.0` with robust error handling and re-enumeration logic.
- **16-bit Raw Output**: Streams pure 16-bit thermal data (Y16) to `/dev/video10`, preserving full radiometric precision for scientific analysis.
- **Visible Stream**: Streams 640x480 visible video to `/dev/video11` (MJPEG), with tearing fixes implemented.
- **Zero-Config Startup**: Single script (`start.sh`) handles module loading, compilation, and permissions.
- **Scientific Suite**:
    - **Radiometric Spot Meter**: Click anywhere to get temperature readings with emissivity correction.
    - **Hot/Cold Tracking**: Auto-track min/max temperature points.
    - **High-Fidelity MSX**: "Edge Fusion" mode with adjustable alignment and scale, using a Difference-of-Gaussians filter for clear text/edge overlay.
- **Dual Viewers**:
  - **Web Viewer**: Flask-based browser interface (perfect for headless/remote usage).
  - **Desktop Viewer**: Fast OpenCV application with real-time colormapping (Iron, Rainbow, Grayscale).

## Quick Start (The Easy Way)

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/your-username/flirone-pro-lt-linux.git
    cd flirone-pro-lt-linux
    ```

2.  **Install Dependencies**:
    ```bash
    sudo apt-get update
    sudo apt-get install build-essential libusb-1.0-0-dev v4l2loopback-dkms python3-venv ffmpeg
    ```

3.  **Run It!**
    *   **For Web Viewer (Recommended)**:
        ```bash
        ./start.sh web
        ```
        Then open **http://localhost:5000** in your browser.

    *   **For Desktop Viewer**:
        ```bash
        ./start.sh
        ```

*Note: The script will ask for your `sudo` password to load kernel modules and set permissions.*

## Architecture

*   **Driver** (`driver/flirone.c`): 
    *   Handles USB bulk transfers (EP 0x85).
    *   Extracts proprietary frame packets (Magic `EF BE`).
    *   Outputs Y16 Thermal -> `/dev/video10` (default)
    *   Outputs MJPEG Visible -> `/dev/video11` (default)
    *   *See [docs/driver_internals.md](docs/driver_internals.md) for detailed protocol documentation.*
*   **Web Viewer** (`examples/web_viewer.py`):
    *   Flask server that reads Y16 and MJPEG data.
    *   **Pass-Through Visible**: Streams raw MJPEG from driver to browser (Zero latency/tearing).
    *   **Hotspot/Coldspot**: Live tracking of min/max temperatures.
    *   **Configurable Palettes**: Toggle between thermal palettes.

## Configuration

### Automatic Device Discovery (Default)
The driver automatically finds the correct video devices by scanning for `v4l2loopback` labels (`FLIR_Thermal` and `FLIR_Visible`). You generally do NOT need to configure anything.

### Manual Video Device IDs
If you need to force specific device IDs (e.g., to resolve conflicts or for static mapping), edit `start.sh`:

```bash
# start.sh
# Set specific numbers to force assignment (e.g., /dev/video20, /dev/video21)
LOOPBACK_THERMAL_NR=20
LOOPBACK_VISIBLE_NR=21
```

The script will automatically reload `v4l2loopback` with the new IDs and pass them to the driver and web viewer.

*   **Desktop Viewer** (`examples/simple_viewer.py`):
    *   Direct OpenCV implementation.
    *   Fast rendering with `cv2.imshow`.

## Troubleshooting

- **"Device Not Found"**: The driver includes an auto-retry loop. If it fails, unplug and replug the camera, then run `lsusb` to verify it appears (ID `09cb:1996`).
- **"Green Tearing / Glitching Video"**: The driver uses robust 64KB padding and double-buffering. If it persists, restart with `./start.sh` to ensure `v4l2loopback` is loaded with `max_buffers=2`.
- **"Temperature Errors (>1000C or Negative)"**: Ensure `camera_config.json` exists in the project root and is readable. The `PlanckO` (Offset) should be `0` and `PlanckR1` (Gain) around `500000` for this sensor.
- **"Permission Denied"**: `start.sh` automatically runs `chmod 666` on the video devices. If you face issues, ensure your user is in the `video` group or run the script again. If `camera_config.json` was created by root, run `sudo chown $USER:$USER camera_config.json`.
- **"Select Timeout"**: If the web viewer hangs, press `Ctrl+C` and restart `start.sh`.

## License
MIT Open Source. Based on community reverse engineering efforts.
