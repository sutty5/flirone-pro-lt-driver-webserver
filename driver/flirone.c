/*
 * FLIR One Pro LT Linux Driver
 * 
 * Clean implementation based on reverse engineering of the original flirone-v4l2.
 * Outputs raw thermal (16-bit) and visible (JPEG) data.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <libusb-1.0/libusb.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>

/* USB Device */
#define VENDOR_ID   0x09CB
#define PRODUCT_ID  0x1996
#define USB_CONFIG  3

/* Frame dimensions (Pro LT = Gen3 = 80x60) */
#define THERMAL_WIDTH   80
#define THERMAL_HEIGHT  60
#define VISIBLE_WIDTH   640
#define VISIBLE_HEIGHT  480

/* Frame format */
#define HEADER_SIZE     28
#define MAGIC_0         0xEF
#define MAGIC_1         0xBE
#define LINE_STRIDE     82  /* 80 * 164 / 160 */
#define LINE_OFFSET     32

/* Buffer size - must be 1MB per original driver */
#define BUFFER_SIZE     1048576

/* V4L2 devices */
#define VIDEO_THERMAL   "/dev/video10"
#define VIDEO_VISIBLE   "/dev/video11"

/* Global state */
static libusb_device_handle *dev = NULL;
static int fd_thermal = -1;
static int fd_visible = -1;
static volatile int running = 1;

/* Frame buffer - like original driver */
static unsigned char buf85[BUFFER_SIZE];
static int buf85pointer = 0;
static int frame_count = 0;

/* Signal handler */
void signal_handler(int sig) {
    printf("\nShutting down...\n");
    running = 0;
}

/* Open V4L2 loopback device */
int open_v4l2_output(const char *device, int width, int height, int format) {
    int fd = open(device, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "Cannot open %s: %s\n", device, strerror(errno));
        return -1;
    }
    
    struct v4l2_format fmt = {0};
    fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = format;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    
    if (format == V4L2_PIX_FMT_GREY) {
        fmt.fmt.pix.bytesperline = width;
        fmt.fmt.pix.sizeimage = width * height;
    } else if (format == V4L2_PIX_FMT_Y16) {
        fmt.fmt.pix.bytesperline = width * 2;
        fmt.fmt.pix.sizeimage = width * height * 2;
    } else if (format == V4L2_PIX_FMT_MJPEG) {
        fmt.fmt.pix.sizeimage = BUFFER_SIZE;
    } else if (format == V4L2_PIX_FMT_RGB24) {
        fmt.fmt.pix.bytesperline = width * 3;
        fmt.fmt.pix.sizeimage = width * height * 3;
    }
    
    if (ioctl(fd, VIDIOC_S_FMT, &fmt) < 0) {
        fprintf(stderr, "Cannot set format on %s: %s\n", device, strerror(errno));
        close(fd);
        return -1;
    }
    
    printf("Opened %s: %dx%d\n", device, width, height);
    return fd;
}

/* Initialize USB device */
int init_usb(void) {
    int r;
    
    r = libusb_init(NULL);
    if (r < 0) {
        fprintf(stderr, "Failed to init libusb: %s\n", libusb_error_name(r));
        return -1;
    }
    
    libusb_init(NULL); // Assuming init success from before or handle error properly
    
    // Retry finding device for 5 seconds
    for (int i = 0; i < 50; i++) {
        dev = libusb_open_device_with_vid_pid(NULL, VENDOR_ID, PRODUCT_ID);
        if (dev) break;
        if (i == 0) printf("Waiting for device...\n");
        usleep(100000); // 100ms
    }
    
    if (!dev) {
        fprintf(stderr, "FLIR One Pro LT not found. Is it connected?\n");
        return -1;
    }
    printf("Found FLIR One Pro LT\n");
    

    
    r = libusb_set_configuration(dev, USB_CONFIG);
    if (r < 0 && r != LIBUSB_ERROR_BUSY) {
        fprintf(stderr, "Cannot set config: %s\n", libusb_error_name(r));
    }
    printf("Set USB configuration %d\n", USB_CONFIG);
    
    for (int i = 0; i < 3; i++) {
        libusb_detach_kernel_driver(dev, i);
        r = libusb_claim_interface(dev, i);
        if (r < 0) {
            fprintf(stderr, "Cannot claim interface %d: %s\n", i, libusb_error_name(r));
            return -1;
        }
    }
    printf("Claimed interfaces 0, 1, 2\n");
    
    return 0;
}

/* Start video streaming */
int start_streaming(void) {
    int r;
    unsigned char data[2] = {0, 0};
    
    printf("stop interface 2 FRAME\n");
    r = libusb_control_transfer(dev, 1, 0x0b, 0, 2, data, 0, 100);
    
    printf("stop interface 1 FILEIO\n");
    r = libusb_control_transfer(dev, 1, 0x0b, 0, 1, data, 0, 100);
    
    printf("\nstart interface 1 FILEIO\n");
    r = libusb_control_transfer(dev, 1, 0x0b, 1, 1, data, 0, 100);
    if (r < 0) {
        fprintf(stderr, "Control error: %s\n", libusb_error_name(r));
        return -1;
    }
    
    printf("\nAsk for video stream, start EP 0x85:\n");
    r = libusb_control_transfer(dev, 1, 0x0b, 1, 2, data, 2, 200);
    if (r < 0) {
        fprintf(stderr, "Control error: %s\n", libusb_error_name(r));
        return -1;
    }
    
    printf("Video streaming started\n");
    return 0;
}

/* Process EP 0x85 data - matches original driver logic exactly */
void vframe(int r, int actual_length, unsigned char *buf) {
    /* Error handling */
    if (r < 0) {
        return;
    }
    
    /* Magic bytes check */
    unsigned char magicbyte[4] = {0xEF, 0xBE, 0x00, 0x00};
    
    /* Reset buffer if new frame starts OR buffer overflow */
    if ((memcmp(buf, magicbyte, 4) == 0) || ((buf85pointer + actual_length) >= BUFFER_SIZE)) {
        buf85pointer = 0;
    }
    
    /* Append chunk to buffer */
    memcpy(buf85 + buf85pointer, buf, actual_length);
    buf85pointer += actual_length;
    
    /* Check if buffer starts with magic bytes */
    if (memcmp(buf85, magicbyte, 4) != 0) {
        buf85pointer = 0;
        return;
    }
    
    /* Need header to parse sizes */
    if (buf85pointer < 28) return;
    
    /* Parse header (little-endian) */
    uint32_t FrameSize = buf85[8] | (buf85[9] << 8) | (buf85[10] << 16) | (buf85[11] << 24);
    uint32_t ThermalSize = buf85[12] | (buf85[13] << 8) | (buf85[14] << 16) | (buf85[15] << 24);
    uint32_t JpgSize = buf85[16] | (buf85[17] << 8) | (buf85[18] << 16) | (buf85[19] << 24);
    
    /* Wait for complete frame */
    if ((FrameSize + 28) > (uint32_t)buf85pointer) {
        return;
    }
    
    /* Got complete frame! */
    frame_count++;
    printf("Frame %d: thermal=%u jpeg=%u\n", frame_count, ThermalSize, JpgSize);
    
    /* Reset pointer for next frame */
    buf85pointer = 0;
    
    /* Extract and write thermal data (16-bit raw) */
    if (ThermalSize > 0 && fd_thermal >= 0) {
        int x, y, v;
        unsigned short pix[THERMAL_WIDTH * THERMAL_HEIGHT];
        
        /* Extract 16-bit raw values */
        for (y = 0; y < THERMAL_HEIGHT; y++) {
            for (x = 0; x < THERMAL_WIDTH; x++) {
                int idx = 2 * (y * LINE_STRIDE + x) + LINE_OFFSET;
                
                /* Range check to be safe */
                if (idx + 1 >= BUFFER_SIZE) continue;
                
                if (x < 80) {
                    v = buf85[idx] + 256 * buf85[idx + 1];
                } else {
                    v = buf85[idx + 4] + 256 * buf85[idx + 1 + 4];
                }
                pix[y * THERMAL_WIDTH + x] = v;
            }
        }
        
        /* Write 16-bit raw thermal data directly */
        write(fd_thermal, pix, sizeof(pix));
    }
    
    /* Write visible JPEG */
    if (JpgSize > 0 && fd_visible >= 0) {
        unsigned char *jpg_data = &buf85[28 + ThermalSize];
        
        /* Verify JPEG SOI (FF D8) */
        if (jpg_data[0] != 0xFF || jpg_data[1] != 0xD8) {
             printf("Warning: Malformed JPEG header\n");
        }
        
        /* Write full JPEG buffer size as reported by header, PLUS PADDING */
        /* Padding fixes 'overread' errors in OpenCV/FFmpeg decoders */
        unsigned char *padded_jpg = malloc(JpgSize + 128);
        if (padded_jpg) {
            memcpy(padded_jpg, jpg_data, JpgSize);
            memset(padded_jpg + JpgSize, 0, 128);
            write(fd_visible, padded_jpg, JpgSize + 128);
            free(padded_jpg);
        } else {
            write(fd_visible, jpg_data, JpgSize);
        }
    }
}

/* Main read loop */
void run_loop(void) {
    unsigned char buf[BUFFER_SIZE];
    int actual;
    int r;
    
    printf("Reading from camera...\n");
    
    while (running) {
        /* Poll EP 0x85 (frame data) - 100ms timeout */
        r = libusb_bulk_transfer(dev, 0x85, buf, sizeof(buf), &actual, 100);
        if (actual > 0) {
            vframe(r, actual, buf);
        }
        
        /* Poll EP 0x81 (status) */
        r = libusb_bulk_transfer(dev, 0x81, buf, sizeof(buf), &actual, 10);
        
        /* Poll EP 0x83 (file I/O) - detects disconnect */
        r = libusb_bulk_transfer(dev, 0x83, buf, sizeof(buf), &actual, 10);
        if (r == LIBUSB_ERROR_NO_DEVICE) {
            fprintf(stderr, "Device disconnected\n");
            break;
        }
    }
}

/* Cleanup */
void cleanup(void) {
    if (dev) {
        unsigned char data[2] = {0, 0};
        libusb_control_transfer(dev, 1, 0x0b, 0, 2, data, 0, 100);
        libusb_control_transfer(dev, 1, 0x0b, 0, 1, data, 0, 100);
        
        for (int i = 0; i < 3; i++) {
            libusb_release_interface(dev, i);
        }
        libusb_reset_device(dev);
        libusb_close(dev);
    }
    libusb_exit(NULL);
    
    if (fd_thermal >= 0) close(fd_thermal);
    if (fd_visible >= 0) close(fd_visible);
    
    printf("Cleanup complete\n");
}

int main(int argc, char **argv) {
    printf("FLIR One Pro LT Driver\n");
    printf("======================\n\n");
    
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    if (init_usb() < 0) {
        return 1;
    }
    
    /* Open V4L2 devices - thermal as 16-bit raw (Y16) */
    fd_thermal = open_v4l2_output(VIDEO_THERMAL, THERMAL_WIDTH, THERMAL_HEIGHT, V4L2_PIX_FMT_Y16);
    fd_visible = open_v4l2_output(VIDEO_VISIBLE, VISIBLE_WIDTH, VISIBLE_HEIGHT, V4L2_PIX_FMT_MJPEG);
    
    if (fd_thermal < 0 && fd_visible < 0) {
        fprintf(stderr, "No output devices available\n");
        cleanup();
        return 1;
    }
    
    if (start_streaming() < 0) {
        cleanup();
        return 1;
    }
    
    run_loop();
    cleanup();
    
    return 0;
}
