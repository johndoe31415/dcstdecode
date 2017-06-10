# dcstdecode
This is a small tool that allows for certain dashcams to re-render the
subtitles which the camera includes into recorded video. The included subtitles
are (for whatever reason) obfuscated so they're not directly useful. However
they do contain information that is not directly renderd in the image (e.g.,
the G-forces in all three directions). This program takes such a video, reads
and decodes the subtitles and then re-render them according to a user-given
rendering string. It's fairly straightforward:

```bash
usage: dcstdecode.py [-h] [-r RENDER_STRING] [-v] infile outfile

positional arguments:
  infile                Dash cam input file.
  outfile               Dash cam output file with custom rendered subtitles.

optional arguments:
  -h, --help            show this help message and exit
  -r RENDER_STRING, --render-string RENDER_STRING
                        printf-style format string according to which new
                        subtitles shall be rendered. Defaults to "%(gx).2f
                        %(gy).2f %(gz).2f %(v_kmh).0f km/h". Valid rendering
                        variables are gx, gy, gz, v_kmh.
  -v, --verbose         Be more verbose during conversion. Can be specified
                        multiple times to increase verbosity.
```

Dependencies
============
dcstdecode relies on ffmpeg for all subtitle transformations.

Compatible cameras
==================
Currently, the camera only works with my dashcam. I have a noname camera, so
it's hard to tell the manufacturer: The display shows "junsun", the camera
"blueskysea". It's using an Ambarella A7LA70 processor and is also referred to
as A7810 or B47FS-D1. It uses the OV4689 image sensor. I do have the suspicion
that this camera is a rebranded Shenzen Dome / Blackview G90 camera (they
certainly look very similar and have similar specs). You'd have to try.

Acknowledgments
===============
Many thanks to Moritz Barsnick who helped me out on the ffmpeg-user mailing
list to figure out how exactly to extract subtitles.

License
=======
dcstdecode is released under the GNU GPL-3.

Data format
===========
For documentation purposes, here's how the subtitles are encoded for my
particular camera. Every line of data looks like this:

```
124	-1008	-362	$GPRMC,102936.000,A,4841.1110,N,00900.5670,E,17.53,221.01,030617,,,0*26
```

The first three digits are the X, Y and Z g-forces in milli-gs. I.e., you
simply have to divide them by 1000 to get the G-force for each axis. What
follows is a standard GPRMC NMEA GPS record (recommended minimum specific
GPS/transit data). If you decode above record, you get:

```
gforce_x = 0.124 
gforce_y = -1.008
gforce_z = -0.362
gps = GPSData(
    2017-06-03 10:29:36, 
    32 km/h, 
    221°, 
    N48.6852° E9.0094°
)
```

That information is also shown when you increase verbosity. The whole record is
obfuscated by a simple Caesar cipher. That is, every character has a
particular, constant offset. That offset is also transmitted in certain
messages as just a plain number:

```
723954862
```

To get the character offset to decode messages, the algorithm that I've reverse
enineered appears to be the sum of digits [ 0 : 8 ], but digits at offset 4 and
7 are counted twice. So for the given example:

```
7 + 2 + 3 + 9 + (2 * 5) + 4 + 8 + (2 * 6) = 55
```

Every message would be shifted by 55 positions. So the string "102936.000"
would, for example, become "hgipjmeggg".

dcstdecode does not bother using this "key". Instead, it uses a known-plaintext
attack on every message because we know that it will always contain the string
"GPRMC". This works better because for continued recording, sometimes data
frame subtitles are embedded before the actual key is transmitted (and that key
is only valid for *following* frames). By our known-plaintext approach we can
also decode those first few subtitles.

