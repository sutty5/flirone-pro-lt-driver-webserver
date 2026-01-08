# flirone-pro-lt-linux

A robust, reverse-engineered driver for the **FLIR One Pro LT** thermal camera on Linux.  
This project unlocks the full potential of your device by outputting **16-bit Raw Radiometric Data** and providing modern visualization tools for both Desktop and Web.

## Features

- **Stable C Driver**: Reverse-engineered USB driver built on `libusb-1.0` with robust error handling and re-enumeration logic.
- **16-bit Raw Output**: Streams pure 16-bit thermal data (Y16) to `/dev/video10`, preserving full radiometric precision for scientific analysis.
- **Visible Stream**: Streams 640x480 visible video to `/dev/video11` (MJPEG), with tearing fixes implemented.
- **Zero-Config Startup**: Single script (`start.sh`) handles module loading, compilation, and permissions.
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
    *   Outputs Y16 Thermal -> `/dev/video10`
    *   Outputs MJPEG Visible -> `/dev/video11`
    *   *See [docs/driver_internals.md](docs/driver_internals.md) for detailed protocol documentation.*
*   **Web Viewer** (`examples/web_viewer.py`):
    *   Flask server that reads Y16 data.
    *   Applies server-side colormapping.
    *   Streams MJPEG to browser.
*   **Desktop Viewer** (`examples/simple_viewer.py`):
    *   Direct OpenCV implementation.
    *   Fast rendering with `cv2.imshow`.

## Troubleshooting

- **"Device Not Found"**: The driver includes an auto-retry loop. If it fails, unplug and replug the camera, then run `lsusb` to verify it appears (ID `09cb:1996`).
- **"Permission Denied"**: `start.sh` automatically runs `chmod 666` on the video devices. If you face issues, ensure your user is in the `video` group or run the script again.
- **"Select Timeout"**: If the web viewer hangs, press `Ctrl+C` and restart `start.sh`.

## License
MIT Open Source. Based on community reverse engineering efforts.
