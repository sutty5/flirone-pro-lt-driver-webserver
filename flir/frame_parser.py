"""
Frame parser for FLIR One Pro LT data stream.

Handles magic byte synchronization and frame structure parsing.
"""

import struct
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np

# Magic bytes that mark the start of each frame
MAGIC_BYTES = bytes([0xEF, 0xBE, 0x00, 0x00])

# Frame dimensions for Pro LT (Gen 3)
THERMAL_WIDTH = 80
THERMAL_HEIGHT = 60
THERMAL_PIXELS = THERMAL_WIDTH * THERMAL_HEIGHT

# Header size (bytes before thermal data)
HEADER_SIZE = 28


@dataclass
class ParsedFrame:
    """Parsed frame data from the camera."""
    
    thermal_raw: np.ndarray  # 16-bit raw thermal data (80x60)
    visible_jpeg: Optional[bytes]  # JPEG data from visible camera
    status_data: Optional[bytes]  # Camera status/calibration data
    frame_size: int
    thermal_size: int
    jpeg_size: int
    status_size: int


class FrameParser:
    """Parses raw USB data into thermal and visible frames."""
    
    def __init__(self, buffer_size: int = 1048576):
        self.buffer = bytearray(buffer_size)
        self.buffer_ptr = 0
        self.buffer_size = buffer_size
        
    def add_chunk(self, data: bytes) -> Optional[ParsedFrame]:
        """Add a chunk of USB data and try to parse a complete frame.
        
        Args:
            data: Raw bytes from USB bulk transfer
            
        Returns:
            ParsedFrame if a complete frame is available, None otherwise
        """
        if not data:
            return None
        
        # Check for buffer overflow, resync if needed
        if self.buffer_ptr + len(data) >= self.buffer_size:
            self._resync_from_chunk(data)
            return None
        
        # Append data to buffer
        self.buffer[self.buffer_ptr:self.buffer_ptr + len(data)] = data
        self.buffer_ptr += len(data)
        
        # Ensure buffer starts with magic bytes
        if self.buffer_ptr >= 4:
            if self.buffer[:4] != MAGIC_BYTES:
                self._resync_buffer()
                return None
        else:
            return None  # Not enough data for magic bytes
        
        # Try to parse frame
        return self._try_parse_frame()
    
    def _resync_buffer(self):
        """Scan buffer for next magic bytes and resync."""
        pos = self._find_magic(bytes(self.buffer[1:self.buffer_ptr]), 0)
        if pos >= 0:
            pos += 1  # Offset for starting at index 1
            # Shift buffer
            remaining = self.buffer_ptr - pos
            self.buffer[:remaining] = self.buffer[pos:self.buffer_ptr]
            self.buffer_ptr = remaining
        else:
            # Keep last 3 bytes in case magic spans chunks
            keep = min(3, self.buffer_ptr)
            self.buffer[:keep] = self.buffer[self.buffer_ptr - keep:self.buffer_ptr]
            self.buffer_ptr = keep
    
    def _resync_from_chunk(self, data: bytes):
        """Handle buffer overflow by resyncing from new chunk."""
        pos = self._find_magic(data, 0)
        if pos >= 0:
            remaining = len(data) - pos
            if remaining > self.buffer_size:
                remaining = self.buffer_size
            self.buffer[:remaining] = data[pos:pos + remaining]
            self.buffer_ptr = remaining
        else:
            keep = min(3, len(data))
            self.buffer[:keep] = data[-keep:]
            self.buffer_ptr = keep
    
    def _find_magic(self, data: bytes, start: int) -> int:
        """Find position of magic bytes in data."""
        try:
            return data.index(MAGIC_BYTES, start)
        except ValueError:
            return -1
    
    def _try_parse_frame(self) -> Optional[ParsedFrame]:
        """Attempt to parse a complete frame from the buffer."""
        if self.buffer_ptr < HEADER_SIZE + 4:
            return None  # Not enough data for header
        
        # Parse header (little-endian uint32 values)
        # Offset 8: Frame size (total payload after header)
        # Offset 12: Thermal data size
        # Offset 16: JPEG size
        # Offset 20: Status size
        frame_size = struct.unpack_from('<I', self.buffer, 8)[0]
        thermal_size = struct.unpack_from('<I', self.buffer, 12)[0]
        jpeg_size = struct.unpack_from('<I', self.buffer, 16)[0]
        status_size = struct.unpack_from('<I', self.buffer, 20)[0]
        
        # Sanity checks
        if frame_size == 0 or frame_size + HEADER_SIZE > self.buffer_size:
            self.buffer_ptr = 0
            return None
        
        total_needed = HEADER_SIZE + frame_size
        if self.buffer_ptr < total_needed:
            return None  # Wait for more data
        
        # Additional sanity check
        if HEADER_SIZE + thermal_size + jpeg_size > self.buffer_ptr:
            self.buffer_ptr = 0
            return None
        
        # Extract thermal data (16-bit big-endian values)
        thermal_start = HEADER_SIZE
        thermal_end = thermal_start + thermal_size
        thermal_bytes = bytes(self.buffer[thermal_start:thermal_end])
        
        # Parse as 16-bit big-endian (">H"), reshape to image
        expected_pixels = THERMAL_WIDTH * THERMAL_HEIGHT
        if len(thermal_bytes) >= expected_pixels * 2:
            thermal_raw = np.frombuffer(thermal_bytes[:expected_pixels * 2], dtype='>u2')
            thermal_raw = thermal_raw.reshape((THERMAL_HEIGHT, THERMAL_WIDTH))
        else:
            # Fallback: use available data
            thermal_raw = np.zeros((THERMAL_HEIGHT, THERMAL_WIDTH), dtype=np.uint16)
        
        # Extract JPEG data
        jpeg_start = thermal_end
        jpeg_end = jpeg_start + jpeg_size
        visible_jpeg = bytes(self.buffer[jpeg_start:jpeg_end]) if jpeg_size > 0 else None
        
        # Extract status data
        status_start = jpeg_end
        status_end = status_start + status_size
        status_data = bytes(self.buffer[status_start:status_end]) if status_size > 0 else None
        
        # Create parsed frame
        frame = ParsedFrame(
            thermal_raw=thermal_raw,
            visible_jpeg=visible_jpeg,
            status_data=status_data,
            frame_size=frame_size,
            thermal_size=thermal_size,
            jpeg_size=jpeg_size,
            status_size=status_size
        )
        
        # Remove processed data from buffer
        consumed = total_needed
        remaining = self.buffer_ptr - consumed
        if remaining > 0:
            self.buffer[:remaining] = self.buffer[consumed:self.buffer_ptr]
        self.buffer_ptr = remaining
        
        return frame
    
    def reset(self):
        """Clear the buffer."""
        self.buffer_ptr = 0
