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

echo "=== FLIR One Pro LT Launcher ==="

# 0. Request sudo permissions upfront
echo "Requesting administrative privileges..."
sudo -v

# Keep sudo alive in background
( while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null & )

# 1. Ensure v4l2loopback is loaded properly
if ! lsmod | grep -q v4l2loopback; then
    echo "Loading v4l2loopback module..."
    sudo modprobe v4l2loopback video_nr=10,11 card_label="FLIR_Thermal,FLIR_Visible" exclusive_caps=1,1
else
    # Check if correct devices exist
    if [ ! -e /dev/video10 ] || [ ! -e /dev/video11 ]; then
        echo "Reloading v4l2loopback module..."
        sudo rmmod v4l2loopback 2>/dev/null || true
        sudo modprobe v4l2loopback video_nr=10,11 card_label="FLIR_Thermal,FLIR_Visible" exclusive_caps=1,1
    fi
fi

# Ensure permissions allow user access
sudo chmod 666 /dev/video10 /dev/video11 2>/dev/null || true

# 2. Build Driver (just in case)
echo "Checking driver build..."
make -C "$DIR/driver" -s

# 3. Start C Driver in background
echo "Starting C Driver..."
sudo "$DIR/driver/flirone" &
DRIVER_PID=$!

# Wait a moment for driver to initialize
sleep 2

# Check if driver is still running
if ! ps -p $DRIVER_PID > /dev/null; then
    echo "Error: Driver failed to start"
    exit 1
fi

# 4. Start Viewer
if [ "$1" == "web" ]; then
    echo "Starting Web Viewer..."
    echo "Open http://localhost:5000 in your browser."
    if [ -d "$DIR/.venv" ]; then
        source "$DIR/.venv/bin/activate"
        python "$DIR/examples/web_viewer.py"
    else
        echo "Error: Virtual environment not found."
        exit 1
    fi
else
    echo "Starting Desktop Viewer..."
    if [ -d "$DIR/.venv" ]; then
        source "$DIR/.venv/bin/activate"
        python "$DIR/examples/simple_viewer.py"
    else
        echo "Error: Virtual environment not found."
        exit 1
    fi
fi
