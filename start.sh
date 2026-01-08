#!/bin/bash
# Start FLIR One Pro LT Driver and Viewer

# Directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Cleanup function
cleanup() {
    echo ""
    echo "Stopping driver..."
    if [ -n "$DRIVER_PID" ]; then
        sudo kill $DRIVER_PID 2>/dev/null
    fi
    exit
}

# Kill any existing driver instances first
echo "Cleaning up old processes..."
sudo pkill -9 flirone 2>/dev/null || true

# Trap signals for cleanup
trap cleanup SIGINT SIGTERM EXIT

# Fail on any error
set -e

# --- Configuration ---
# You can leave these empty to let the system pick available devices automatically
LOOPBACK_THERMAL_NR=""
LOOPBACK_VISIBLE_NR=""

echo "=== FLIR One Pro LT Launcher ==="

# Check if we are running as root (needed for modprobe) or can use sudo
if [ "$EUID" -ne 0 ]; then
  echo "Requesting administrative privileges..."
  sudo -v
  # Keep sudo alive in background
  ( while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null & )
fi

# 1. Ensure v4l2loopback is loaded properly
# We ask for specific labels so we can find them later
REQUIRED_LABELS="FLIR_Thermal,FLIR_Visible"

if ! lsmod | grep -q v4l2loopback; then
    echo "Loading v4l2loopback module..."
    # If IDs are set, use them. Otherwise let module pick.
    VIDEO_NR_ARG=""
    if [ ! -z "$LOOPBACK_THERMAL_NR" ] && [ ! -z "$LOOPBACK_VISIBLE_NR" ]; then
        VIDEO_NR_ARG="video_nr=$LOOPBACK_THERMAL_NR,$LOOPBACK_VISIBLE_NR"
    fi
    sudo modprobe v4l2loopback $VIDEO_NR_ARG card_label="$REQUIRED_LABELS" exclusive_caps=1,1 max_buffers=2
else
    # Check if labels exist in current module
    if ! grep -q "FLIR_Thermal" /sys/class/video4linux/*/name 2>/dev/null; then
        echo "Reloading v4l2loopback (missing correct labels)..."
        sudo rmmod v4l2loopback 2>/dev/null || true
        sudo modprobe v4l2loopback card_label="$REQUIRED_LABELS" exclusive_caps=1,1 max_buffers=2
    fi
fi

# 1.5 Auto-Discover Devices by Label
find_device_by_label() {
    local label=$1
    for dev in /sys/class/video4linux/*; do
        if [ -e "$dev/name" ]; then
            local name=$(cat "$dev/name")
            if [ "$name" == "$label" ]; then
                # /sys/class/video4linux/videoN -> /dev/videoN
                echo "/dev/$(basename $dev)"
                return 0
            fi
        fi
    done
    return 1
}

DEV_THERMAL=$(find_device_by_label "FLIR_Thermal")
DEV_VISIBLE=$(find_device_by_label "FLIR_Visible")

if [ -z "$DEV_THERMAL" ] || [ -z "$DEV_VISIBLE" ]; then
    echo "Error: Could not find FLIR loopback devices. Driver load failed?"
    exit 1
fi

echo "Found Devices:"
echo "  [Thermal] -> $DEV_THERMAL"
echo "  [Visible] -> $DEV_VISIBLE"

# Allow user access to video devices
sudo chmod 666 $DEV_THERMAL $DEV_VISIBLE || true

# 2. Build Driver if needed
echo "Checking driver build..."
cd "$DIR/driver"
make > /dev/null
cd "$DIR"

# 3. Handle Cleanup on Exit
cleanup() {
    echo ""
    echo "Shutting down..."
    # Kill the driver specifically if it's running
    if [ -n "$DRIVER_PID" ]; then
        sudo kill $DRIVER_PID 2>/dev/null
    fi
    # Kill any child processes started by this script
    pkill -P $$ || true
}
trap cleanup EXIT

# 4. Start C Driver
echo "Starting C Driver..."
# Pass device paths as arguments
sudo "$DIR/driver/flirone" $DEV_THERMAL $DEV_VISIBLE &
DRIVER_PID=$!

# Wait for driver to initialize
sleep 2

if ! kill -0 $DRIVER_PID 2>/dev/null; then
    echo "Error: Driver failed to start"
    exit 1
fi

# 5. Start Viewer (Optional)
if [ "$1" == "web" ]; then
    echo "Starting Web Viewer..."
    echo "Open http://localhost:5000 in your browser."
    # Pass device paths as environment variables
    export FLIR_THERMAL_DEVICE=$DEV_THERMAL
    export FLIR_VISIBLE_DEVICE=$DEV_VISIBLE
    if [ -d "$DIR/.venv" ]; then
        source "$DIR/.venv/bin/activate"
        export PYTHONPATH="$DIR"
        python3 "$DIR/examples/web_viewer.py"
    else
        echo "Error: Virtual environment not found."
        exit 1
    fi
else
    echo "Starting Desktop Viewer..."
    if [ -d "$DIR/.venv" ]; then
        source "$DIR/.venv/bin/activate"
        export PYTHONPATH="$DIR"
        python "$DIR/examples/simple_viewer.py"
    else
        echo "Error: Virtual environment not found."
        exit 1
    fi
fi
