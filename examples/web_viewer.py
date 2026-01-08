from flask import Flask, Response, render_template_string
import cv2
import numpy as np
import time
from flir.thermal import ThermalContext

app = Flask(__name__)

# Device Configuration
THERMAL_DEVICE = '/dev/video10'
VISIBLE_DEVICE = '/dev/video11'
THERMAL_WIDTH, THERMAL_HEIGHT = 80, 60

# Palette Cache
def create_iron_palette():
    palette = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        if i < 64:
            palette[i] = [i * 2, 0, i * 2]
        elif i < 128:
            t = i - 64
            palette[i] = [128 + t * 2, 0, 128 - t * 2]
        elif i < 192:
            t = i - 128
            palette[i] = [255, t * 4, 0]
        else:
            t = i - 192
            palette[i] = [255, 255, t * 4]
    return palette

PALETTE = create_iron_palette()

def apply_colormap_16bit(frame_16, ctx):
    """Normalize 16-bit frame and apply colormap with radiometry"""
    # Calculate temps
    min_val = frame_16.min()
    max_val = frame_16.max()
    center_val = frame_16[THERMAL_HEIGHT//2, THERMAL_WIDTH//2]
    
    min_temp = ctx.raw2temp(min_val)
    max_temp = ctx.raw2temp(max_val)
    center_temp = ctx.raw2temp(center_val)
    
    # Debug print
    print(f"Frame Stats: Raw={min_val}-{max_val} Temp={min_temp:.1f}C-{max_temp:.1f}C Center={center_temp:.1f}C")
    
    # Avoid divide by zero for normalization
    if max_val > min_val:
        norm = ((frame_16.astype(np.float32) - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
    else:
        norm = np.zeros_like(frame_16, dtype=np.uint8)
    
    # Apply palette (RGB)
    colored = PALETTE[norm]
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
    
    return bgr

def generate_thermal():
    cap = cv2.VideoCapture(THERMAL_DEVICE)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
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
        
        # Handle 16-bit frame
        if frame.dtype == np.uint16:
             gray = frame.view(np.uint16)
        else:
             # Basic fallback check
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
    cap = cv2.VideoCapture(VISIBLE_DEVICE)
    if not cap.isOpened():
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
            
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
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
    </style>
</head>
<body>
    <h1>FLIR One Pro LT Stream</h1>
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
    ''')

@app.route('/video_thermal')
def video_thermal():
    return Response(generate_thermal(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_visible')
def video_visible():
    return Response(generate_visible(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
