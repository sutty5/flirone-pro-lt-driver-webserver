from flask import Flask, Response, render_template_string, request, jsonify
import cv2
import numpy as np
import time
import os
from flir.thermal import ThermalContext
from flir.colormap import load_palette, PALETTE_DIR

app = Flask(__name__)

# Device Configuration
# Device Configuration
THERMAL_DEVICE = os.environ.get('FLIR_THERMAL_DEVICE', '/dev/video10')
VISIBLE_DEVICE = os.environ.get('FLIR_VISIBLE_DEVICE', '/dev/video11')
THERMAL_WIDTH, THERMAL_HEIGHT = 80, 60

# Global State
CURRENT_PALETTE_NAME = "Iron2"
CURRENT_PALETTE = load_palette(CURRENT_PALETTE_NAME)
SHOW_HOTSPOT = True
SHOW_COLDSPOT = True

def get_available_palettes():
    palettes = []
    if os.path.exists(PALETTE_DIR):
        for f in os.listdir(PALETTE_DIR):
            if f.endswith('.raw'):
                palettes.append(f[:-4])
    return sorted(palettes)

def apply_colormap_16bit(frame_16, ctx):
    """Normalize 16-bit frame and apply colormap with radiometry"""
    # Calculate temps
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(frame_16)
    center_val = frame_16[THERMAL_HEIGHT//2, THERMAL_WIDTH//2]
    
    min_temp = ctx.raw2temp(min_val)
    max_temp = ctx.raw2temp(max_val)
    center_temp = ctx.raw2temp(center_val)
    
    # Avoid divide by zero for normalization
    if max_val > min_val:
        norm = ((frame_16.astype(np.float32) - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
    else:
        norm = np.zeros_like(frame_16, dtype=np.uint8)
    
    # Apply palette (RGB)
    # Use global CURRENT_PALETTE
    colored = CURRENT_PALETTE[norm]
    # Convert RGB to BGR for OpenCV encoding
    bgr = colored[:, :, ::-1].copy()
    
    # Upscale
    bgr = cv2.resize(bgr, (640, 480), interpolation=cv2.INTER_NEAREST)
    
    # Draw Info
    # Range
    cv2.putText(bgr, f"Range: {min_temp:.1f}C - {max_temp:.1f}C", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    # Center Spot
    cx, cy = 320, 240
    cv2.drawMarker(bgr, (cx, cy), (200, 200, 200), cv2.MARKER_CROSS, 20, 1)
    cv2.putText(bgr, f"{center_temp:.1f}C", (cx + 10, cy - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
    
    # Scale locations to new size
    scale_x = 640 / THERMAL_WIDTH
    scale_y = 480 / THERMAL_HEIGHT
    
    if SHOW_HOTSPOT:
        hx = int(max_loc[0] * scale_x)
        hy = int(max_loc[1] * scale_y)
        cv2.circle(bgr, (hx, hy), 5, (0, 0, 255), 2)  # Red circle
        cv2.putText(bgr, f"{max_temp:.1f}C", (hx + 10, hy), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    if SHOW_COLDSPOT:
        lx = int(min_loc[0] * scale_x)
        ly = int(min_loc[1] * scale_y)
        cv2.circle(bgr, (lx, ly), 5, (255, 0, 0), 2)  # Blue circle
        cv2.putText(bgr, f"{min_temp:.1f}C", (lx + 10, ly), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 100), 2)
    
    return bgr

def generate_thermal():
    cap = cv2.VideoCapture(THERMAL_DEVICE)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    # Try to set format, but it depends on the driver if this is needed or respected
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y','1','6',' '))
    
    # Initialize Radiometry
    ctx = ThermalContext()
    
    if not cap.isOpened():
        print("Could not open thermal device")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        
        # Handle 16-bit frame logic
        if frame.dtype == np.uint16:
             gray = frame.view(np.uint16)
        else:
             # Basic fallback check for 8-bit containers of 16-bit data
             if frame.shape[1] == THERMAL_WIDTH * 2:
                  gray = frame.view(np.uint16)
             else:
                  gray = frame
        
        # Reshape if needed
        if gray.shape != (THERMAL_HEIGHT, THERMAL_WIDTH):
             try:
                 gray = gray.reshape((THERMAL_HEIGHT, THERMAL_WIDTH))
             except:
                 pass

        final = apply_colormap_16bit(gray, ctx)
        ret, buffer = cv2.imencode('.jpg', final)
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

def generate_visible():
    # Direct Pass-Through: Read raw JPEG from driver, send to browser.
    # No decoding/re-encoding overhead. No OpenCV tearing.
    fd = -1
    try:
        # Open in read-only, non-blocking could be an option but blocking is fine for a thread
        fd = os.open(VISIBLE_DEVICE, os.O_RDONLY)
    except Exception as e:
        print(f"Error opening {VISIBLE_DEVICE}: {e}")
        return

    while True:
        try:
            # v4l2loopback read() returns one complete frame
            # 640x480 MJPEG is usually <100KB. 256KB is plenty safely.
            frame_data = os.read(fd, 256 * 1024)
            
            if not frame_data:
                time.sleep(0.01)
                continue
                
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                   
        except Exception as e:
            # Re-open on error?
            print(f"Error streaming visible: {e}")
            time.sleep(0.1)

@app.route('/')
def index():
    palettes = get_available_palettes()
    return render_template_string('''
<html>
<head>
    <title>FLIR One Pro LT - Web Viewer</title>
    <style>
        body { background: #1a1a1a; color: #eee; font-family: sans-serif; text-align: center; }
        .container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; padding: 20px; }
        .stream { background: #000; padding: 10px; border-radius: 8px; }
        h2 { margin-top: 0; }
        img { max-width: 100%; height: auto; border-radius: 4px; }
        .controls { margin: 20px; padding: 10px; background: #333; border-radius: 8px; display: inline-block; }
        select { padding: 5px; font-size: 16px; border-radius: 4px; }
        .check { margin-left: 20px; display: inline-block; }
        label { margin-left: 5px; cursor: pointer; }
    </style>
    <script>
        function updatePalette(selectObject) {
            var value = selectObject.value;  
            fetch('/api/set_palette?name=' + value)
                .then(response => response.json())
                .then(data => console.log(data));
        }
        function toggleSpot(type, checkbox) {
            fetch('/api/toggle_spot?type=' + type + '&state=' + checkbox.checked)
                .then(response => response.json())
                .then(data => console.log(data));
        }
    </script>
</head>
<body>
    <h1>FLIR One Pro LT Stream</h1>
    
    <div class="controls">
        <label for="palette">Color Palette: </label>
        <select id="palette" onchange="updatePalette(this)">
            {% for p in palettes %}
            <option value="{{ p }}" {% if p == current_palette %}selected{% endif %}>{{ p }}</option>
            {% endfor %}
        </select>
        
        <div class="check">
            <input type="checkbox" id="hotspot" onclick="toggleSpot('hot', this)" {% if show_hot %}checked{% endif %}>
            <label for="hotspot">Show Hotspot</label>
        </div>
        
        <div class="check">
            <input type="checkbox" id="coldspot" onclick="toggleSpot('cold', this)" {% if show_cold %}checked{% endif %}>
            <label for="coldspot">Show Coldspot</label>
        </div>
    </div>

    <div class="container">
        <div class="stream">
            <h2>Thermal (Radiometric °C)</h2>
            <img src="/video_thermal" width="640" height="480">
        </div>
        <div class="stream">
            <h2>Visible</h2>
            <img src="/video_visible" width="640" height="480">
        </div>
    </div>
</body>
</html>
    ''', palettes=palettes, current_palette=CURRENT_PALETTE_NAME, show_hot=SHOW_HOTSPOT, show_cold=SHOW_COLDSPOT)

@app.route('/video_thermal')
def video_thermal():
    return Response(generate_thermal(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_visible')
def video_visible():
    return Response(generate_visible(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/set_palette')
def set_palette():
    global CURRENT_PALETTE, CURRENT_PALETTE_NAME
    name = request.args.get('name')
    if name:
        new_palette = load_palette(name)
        # Simple check if load_palette returned a valid array (it always returns something valid, even if fallback)
        CURRENT_PALETTE = new_palette
        CURRENT_PALETTE_NAME = name
        return jsonify({"status": "ok", "palette": name})
    return jsonify({"status": "error", "message": "No name provided"}), 400

@app.route('/api/toggle_spot')
def toggle_spot():
    global SHOW_HOTSPOT, SHOW_COLDSPOT
    spot_type = request.args.get('type')
    state = request.args.get('state') == 'true'
    
    if spot_type == 'hot':
        SHOW_HOTSPOT = state
    elif spot_type == 'cold':
        SHOW_COLDSPOT = state
    else:
        return jsonify({"status": "error", "message": "Invalid type"}), 400
        
    return jsonify({"status": "ok", "type": spot_type, "state": state})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
