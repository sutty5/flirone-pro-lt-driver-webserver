"""
Colormap support for thermal image visualization.

Loads and applies color palettes to thermal data.
"""

import os
import numpy as np
from typing import Optional

# Default palette directory
PALETTE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "palettes")


def load_palette(name: str = "Iron2") -> np.ndarray:
    """Load a color palette from file.
    
    Args:
        name: Palette name (without .raw extension)
        
    Returns:
        Numpy array of shape (256, 3) with RGB values
    """
    # Try to find palette file
    palette_path = os.path.join(PALETTE_DIR, f"{name}.raw")
    
    if not os.path.exists(palette_path):
        # Try alternate paths
        alt_paths = [
            os.path.join(PALETTE_DIR, name),
            name  # Absolute path
        ]
        for alt in alt_paths:
            if os.path.exists(alt):
                palette_path = alt
                break
        else:
            # Fall back to grayscale
            return np.array([[i, i, i] for i in range(256)], dtype=np.uint8)
    
    # Load raw palette (768 bytes = 256 RGB values)
    with open(palette_path, 'rb') as f:
        data = f.read()
    
    if len(data) < 768:
        # Pad with grayscale if too short
        return np.array([[i, i, i] for i in range(256)], dtype=np.uint8)
    
    # Parse as RGB triplets
    palette = np.frombuffer(data[:768], dtype=np.uint8).reshape((256, 3))
    return palette


def apply_colormap(thermal_8bit: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Apply a color palette to 8-bit thermal data.
    
    Args:
        thermal_8bit: Grayscale thermal image (0-255)
        palette: Color lookup table (256, 3)
        
    Returns:
        Colorized BGR image for OpenCV display
    """
    # Use palette as lookup table
    colored = palette[thermal_8bit]
    
    # Convert RGB to BGR for OpenCV
    return colored[:, :, ::-1].copy()


def normalize_thermal(thermal_raw: np.ndarray, 
                      min_val: Optional[int] = None,
                      max_val: Optional[int] = None) -> np.ndarray:
    """Normalize 16-bit thermal data to 8-bit.
    
    Args:
        thermal_raw: 16-bit thermal data
        min_val: Optional minimum value (auto if None)
        max_val: Optional maximum value (auto if None)
        
    Returns:
        8-bit normalized image (0-255)
    """
    if min_val is None:
        min_val = int(thermal_raw.min())
    if max_val is None:
        max_val = int(thermal_raw.max())
    
    # Avoid division by zero
    range_val = max(1, max_val - min_val)
    
    # Normalize to 0-255
    normalized = ((thermal_raw.astype(np.float32) - min_val) / range_val * 255)
    normalized = np.clip(normalized, 0, 255).astype(np.uint8)
    
    return normalized


# Default palette (loaded lazily)
_default_palette: Optional[np.ndarray] = None


def get_default_palette() -> np.ndarray:
    """Get the default Iron2 palette."""
    global _default_palette
    if _default_palette is None:
        _default_palette = load_palette("Iron2")
    return _default_palette
