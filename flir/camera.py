"""
High-level FLIR camera API.

Provides easy-to-use interface for capturing thermal and visible images.
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional
import numpy as np
import cv2

from .usb_driver import USBDriver
from .frame_parser import FrameParser, ParsedFrame
from .colormap import apply_colormap, normalize_thermal, get_default_palette
from .thermal import raw_to_celsius, get_temperature_stats


@dataclass
class FLIRFrame:
    """A captured frame from the FLIR camera."""
    
    thermal_raw: np.ndarray       # Raw 16-bit thermal data (80x60)
    thermal_8bit: np.ndarray      # Normalized 8-bit thermal
    thermal_colored: np.ndarray   # Colorized BGR image
    visible: Optional[np.ndarray] # Visible camera image (decoded JPEG)
    
    # Statistics
    min_temp_c: float
    max_temp_c: float
    mean_temp_c: float
    hotspot: tuple  # (x, y)
    coldspot: tuple # (x, y)
    
    timestamp: float
    

class FLIRCamera:
    """High-level interface to FLIR One Pro LT camera.
    
    Usage:
        with FLIRCamera() as cam:
            frame = cam.read()
            cv2.imshow("Thermal", frame.thermal_colored)
    """
    
    def __init__(self, palette: str = "Iron2"):
        """Initialize camera.
        
        Args:
            palette: Color palette name (Iron2, Rainbow, Grayscale, etc.)
        """
        self.usb = USBDriver()
        self.parser = FrameParser()
        self.palette = get_default_palette()
        self._connected = False
        self._lock = threading.Lock()
        
    def connect(self) -> bool:
        """Connect to the camera."""
        with self._lock:
            if self._connected:
                return True
            
            try:
                self.usb.open()
                self.parser.reset()
                self._connected = True
                print("FLIR One Pro LT connected")
                return True
            except Exception as e:
                print(f"Failed to connect: {e}")
                return False
    
    def disconnect(self):
        """Disconnect from the camera."""
        with self._lock:
            if self._connected:
                self.usb.close()
                self._connected = False
                print("FLIR One Pro LT disconnected")
    
    def read(self, timeout: float = 1.0) -> Optional[FLIRFrame]:
        """Read a frame from the camera.
        
        Args:
            timeout: Maximum time to wait for a frame (seconds)
            
        Returns:
            FLIRFrame if successful, None on timeout
        """
        if not self._connected:
            return None
        
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            # Read USB data
            data = self.usb.read(timeout=int(timeout * 1000))
            if data is None:
                continue
            
            # Try to parse frame
            parsed = self.parser.add_chunk(data)
            if parsed is not None:
                return self._make_frame(parsed)
        
        return None
    
    def _make_frame(self, parsed: ParsedFrame) -> FLIRFrame:
        """Convert parsed frame to FLIRFrame object."""
        # Normalize thermal to 8-bit
        thermal_8bit = normalize_thermal(parsed.thermal_raw)
        
        # Apply colormap
        thermal_colored = apply_colormap(thermal_8bit, self.palette)
        
        # Decode visible JPEG
        visible = None
        if parsed.visible_jpeg is not None and len(parsed.visible_jpeg) > 100:
            try:
                arr = np.frombuffer(parsed.visible_jpeg, dtype=np.uint8)
                visible = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                pass
        
        # Get temperature statistics
        stats = get_temperature_stats(parsed.thermal_raw)
        
        return FLIRFrame(
            thermal_raw=parsed.thermal_raw,
            thermal_8bit=thermal_8bit,
            thermal_colored=thermal_colored,
            visible=visible,
            min_temp_c=stats['min_c'],
            max_temp_c=stats['max_c'],
            mean_temp_c=stats['mean_c'],
            hotspot=stats['max_location'],
            coldspot=stats['min_location'],
            timestamp=time.time()
        )
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
