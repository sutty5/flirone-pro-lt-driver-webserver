#!/usr/bin/env python3
"""
FLIR One Pro LT Colorized Viewer

Reads raw thermal from v4l2loopback and applies color palettes.
"""

import sys
import os
import cv2
import numpy as np

# Video devices (from C driver)
THERMAL_DEVICE = '/dev/video10'
VISIBLE_DEVICE = '/dev/video11'

# Thermal dimensions
THERMAL_WIDTH = 80
THERMAL_HEIGHT = 60  # Driver outputs 60, but might vary
DISPLAY_SCALE = 8


def create_iron_palette():
    """Create Iron/Hot color palette (black -> purple -> red -> yellow -> white)."""
    palette = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        if i < 64:
            # Black to purple
            palette[i] = [i * 2, 0, i * 2]
        elif i < 128:
            # Purple to red
            t = i - 64
            palette[i] = [128 + t * 2, 0, 128 - t * 2]
        elif i < 192:
            # Red to yellow
            t = i - 128
            palette[i] = [255, t * 4, 0]
        else:
            # Yellow to white
            t = i - 192
            palette[i] = [255, 255, t * 4]
    return palette


def create_rainbow_palette():
    """Create rainbow color palette."""
    palette = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        # HSV to RGB conversion with hue = i/255 * 240 (blue to red)
        hue = int((255 - i) * 240 / 255)  # Reversed so hot = red
        hsv = np.array([[[hue, 255, 255]]], dtype=np.uint8)
        rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        palette[i] = rgb[0, 0]
    return palette


def load_palette_file(path):
    """Load palette from .raw file."""
    try:
        with open(path, 'rb') as f:
            data = f.read(768)
        if len(data) >= 768:
            return np.frombuffer(data, dtype=np.uint8).reshape((256, 3))
    except:
        pass
    return create_iron_palette()


def apply_colormap(thermal_8bit, palette):
    """Apply color palette to 8-bit thermal data."""
    colored = palette[thermal_8bit]
    # Convert RGB to BGR for OpenCV
    return colored[:, :, ::-1].copy()


def main():
    print("FLIR One Pro LT Colorized Viewer")
    print("=" * 40)
    print(f"Thermal: {THERMAL_DEVICE}")
    print(f"Visible: {VISIBLE_DEVICE}")
    print()
    print("Controls:")
    print("  q - Quit")
    print("  1 - Iron palette")
    print("  2 - Rainbow palette")
    print("  3 - Grayscale")
    print("  s - Save snapshot")
    print()
    
    # Load palettes
    palettes = {
        '1': ('Iron', create_iron_palette()),
        '2': ('Rainbow', create_rainbow_palette()),
        '3': ('Gray', np.array([[i, i, i] for i in range(256)], dtype=np.uint8)),
    }
    
    # Try to load Iron2 from file
    iron2_path = os.path.join(os.path.dirname(__file__), '..', 'palettes', 'Iron2.raw')
    if os.path.exists(iron2_path):
        palettes['1'] = ('Iron2', load_palette_file(iron2_path))
    
    current_palette = '1'
    
    # Open thermal capture
    thermal_cap = cv2.VideoCapture(THERMAL_DEVICE)
    if not thermal_cap.isOpened():
        print(f"Cannot open {THERMAL_DEVICE}")
        print("Is the driver running? Run: ./run_driver.sh")
        return 1
    
    # Request raw data (don't convert to RGB)
    thermal_cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    # Hint to OpenCV that we expect Y16 (might not be strictly necessary if v4l2 reports it)
    thermal_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y','1','6',' '))
    
    # Try to open visible
    visible_cap = cv2.VideoCapture(VISIBLE_DEVICE)
    has_visible = visible_cap.isOpened()
    
    print(f"Thermal: OK")
    print(f"Visible: {'OK' if has_visible else 'Not available'}")
    print(f"\nStreaming with {palettes[current_palette][0]} palette...")
    
    frame_count = 0
    while True:
        # Read thermal frame
        ret, frame = thermal_cap.read()
        if not ret:
            continue
        
        frame_count += 1
        
        # Handle frame format
        if len(frame.shape) == 3:
            # If OpenCV converted it anyway, convert back
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif frame.dtype == np.uint16:
            # We got raw 16-bit data!
            gray = frame.view(np.uint16)
        else:
            # 8-bit single channel or raw bytes that need reinterpreting
            if frame.shape[1] == THERMAL_WIDTH * 2:
                # 8-bit bytes representing 16-bit pixels
                gray = frame.view(np.uint16)
            else:
                 gray = frame
        
        # Ensure shape is correct (60, 80)
        if gray.shape != (THERMAL_HEIGHT, THERMAL_WIDTH):
             try:
                 gray = gray.reshape((THERMAL_HEIGHT, THERMAL_WIDTH))
             except ValueError:
                 # Last ditch effort if total pixels match
                 if gray.size == THERMAL_HEIGHT * THERMAL_WIDTH:
                      gray = gray.reshape((THERMAL_HEIGHT, THERMAL_WIDTH))
        
        # Get min/max for normalization
        min_val = gray.min()
        max_val = gray.max()
        
        # Normalize to 0-255
        if max_val > min_val:
            normalized = ((gray.astype(np.float32) - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
        else:
            normalized = np.zeros_like(gray, dtype=np.uint8)
        
        # Apply color palette
        palette_name, palette = palettes[current_palette]
        colored = apply_colormap(normalized, palette)
        
        # Scale up for display
        h, w = colored.shape[:2]
        display_size = (w * DISPLAY_SCALE, h * DISPLAY_SCALE)
        display = cv2.resize(colored, display_size, interpolation=cv2.INTER_NEAREST)
        
        # Draw info
        cv2.putText(display, f"{palette_name} | Range: {min_val}-{max_val}", 
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Find and mark hottest/coldest spots
        min_loc = np.unravel_index(np.argmin(gray), gray.shape)
        max_loc = np.unravel_index(np.argmax(gray), gray.shape)
        
        # Draw hotspot marker (scaled)
        hx, hy = max_loc[1] * DISPLAY_SCALE, max_loc[0] * DISPLAY_SCALE
        cv2.drawMarker(display, (hx, hy), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        cv2.putText(display, "HOT", (hx + 15, hy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        # Draw coldspot marker
        cx, cy = min_loc[1] * DISPLAY_SCALE, min_loc[0] * DISPLAY_SCALE
        cv2.drawMarker(display, (cx, cy), (255, 200, 0), cv2.MARKER_CROSS, 20, 2)
        cv2.putText(display, "COLD", (cx + 15, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 2)
        
        cv2.imshow("FLIR Thermal", display)
        
        # Show visible if available
        if has_visible:
            ret_v, visible = visible_cap.read()
            if ret_v:
                cv2.imshow("FLIR Visible", visible)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif chr(key) in palettes:
            current_palette = chr(key)
            print(f"Switched to {palettes[current_palette][0]} palette")
        elif key == ord('s'):
            cv2.imwrite(f"thermal_{frame_count}.png", colored)
            print(f"Saved thermal_{frame_count}.png")
    
    thermal_cap.release()
    if has_visible:
        visible_cap.release()
    cv2.destroyAllWindows()
    
    print(f"\nTotal frames: {frame_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
