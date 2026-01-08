#!/bin/bash
# Run FLIR One Pro LT driver with v4l2loopback

set -e

echo "=== FLIR One Pro LT Driver ==="

# Ensure v4l2loopback is loaded
if ! lsmod | grep -q v4l2loopback; then
    echo "Loading v4l2loopback..."
    sudo modprobe v4l2loopback video_nr=10,11 card_label="FLIR_Thermal,FLIR_Visible"
    sleep 1
else
    # Check if our devices exist
    if [ ! -e /dev/video10 ] || [ ! -e /dev/video11 ]; then
        echo "Reloading v4l2loopback..."
        sudo rmmod v4l2loopback 2>/dev/null || true
        sudo modprobe v4l2loopback video_nr=10,11 card_label="FLIR_Thermal,FLIR_Visible"
        sleep 1
    fi
fi

echo "Video devices:"
ls -la /dev/video10 /dev/video11 2>/dev/null || echo "Warning: devices not found"

# Run our custom driver
echo "Starting driver..."
cd "$(dirname "$0")/driver"
sudo ./flirone
