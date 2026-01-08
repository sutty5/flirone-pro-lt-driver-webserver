# FLIR One Pro LT Driver
# Minimal C driver for raw thermal and visible output

CC = gcc
CFLAGS = -Wall -O2 -I/usr/include/libusb-1.0
LDFLAGS = -lusb-1.0

TARGET = flirone
SRC = flirone.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)

install:
	cp $(TARGET) /usr/local/bin/

.PHONY: all clean install
