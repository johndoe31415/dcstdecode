#!/usr/bin/python3
#	dcstdecode - Dashcam Subtitle Decoder
#	Copyright (C) 2017-2017 Johannes Bauer
#
#	This file is part of dcstdecode.
#
#	dcstdecode is free software; you can redistribute it and/or modify
#	it under the terms of the GNU General Public License as published by
#	the Free Software Foundation; this program is ONLY licensed under
#	version 3 of the License, later versions are explicitly excluded.
#
#	dcstdecode is distributed in the hope that it will be useful,
#	but WITHOUT ANY WARRANTY; without even the implied warranty of
#	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#	GNU General Public License for more details.
#
#	You should have received a copy of the GNU General Public License
#	along with dcstdecode; if not, write to the Free Software
#	Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import struct
import collections
import re
import datetime
import subprocess
import tempfile
from FriendlyArgumentParser import FriendlyArgumentParser

class GPSData(object):
	_GPS_RE = re.compile("\$GPRMC,(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})(\.(?P<secfract>\d+))?,(?P<havefix>[AV]),(?P<lat_major>\d{2})(?P<lat_minor>\d{2}\.\d+),(?P<lat_sign>[NS]),(?P<long_major>\d{3})(?P<long_minor>\d{2}\.\d+),(?P<long_sign>[WE]),(?P<v_gnd>\d+\.\d+),(?P<true_bearing>\d+\.\d+),(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{2}),(?P<magvar>\d+\.\d+)?,(?P<magvar_sign>[EW])?,(?P<integrity>.)\*(?P<checksum>[A-Fa-f0-9]{2})")
	def __init__(self, gprmc_string):
		self._ts_utc = None
		self._havefix = False
		self._latitude = None
		self._longitude = None
		self._v_gnd_m_s = None
		self._bearing = None
		result = self._GPS_RE.fullmatch(gprmc_string)
		if result is not None:
			result = result.groupdict()
			calculated_checksum = self._xor(gprmc_string[1 : -3].encode("ascii"))
			transmitted_checksum = int(result["checksum"], 16)
			if calculated_checksum == transmitted_checksum:
				(year, month, day, hour, minute, second) = (int(result["year"]) + 2000, int(result["month"]), int(result["day"]), int(result["hour"]), int(result["minute"]), int(result["second"]))
				if result["secfract"] is None:
					microsec = 0
				else:
					microsec = int(result["secfract"]) * 1000
				self._ts_utc = datetime.datetime(year, month, day, hour, minute, second, microsec)
				self._havefix = result["havefix"] == "A"

				lat = int(result["lat_major"])
				lat_minor = float(result["lat_minor"])
				lat_sign = 1 if (result["lat_sign"] == "N") else -1
				lat = lat_sign * (lat + lat_minor / 60)

				long = int(result["long_major"])
				long_minor = float(result["long_minor"])
				long_sign = 1 if (result["long_sign"] == "W") else -1
				long = long_sign * (long + long_minor / 60)

				self._latitude = lat
				self._longitude = long

				self._v_gnd_m_s = float(result["v_gnd"]) * 463 / 900
				self._bearing = float(result["true_bearing"]) % 360

	@property
	def ts_utc(self):
		return self._ts_utc

	@property
	def v_gnd_m_s(self):
		return self._v_gnd_m_s

	@property
	def v_gnd_km_h(self):
		if self.v_gnd_m_s is not None:
			return self.v_gnd_m_s * 3.6

	@property
	def position_fractional(self):
		if (self._latitude is not None) and (self._longitude is not None):
			return "%s%.4f° %s%.4f°" % ("SN"[self._latitude >= 0], abs(self._latitude), "EW"[self._longitude >= 0], abs(self._longitude))

	@property
	def bearing(self):
		return self._bearing

	@staticmethod
	def _xor(data):
		result = 0
		for char in data:
			result ^= char
		return result

	def __repr__(self):
		available = [ ]
		if self.ts_utc is not None:
			available.append(str(self.ts_utc))
		if self.v_gnd_km_h is not None:
			available.append("%.0f km/h" % (self.v_gnd_km_h))
		if self.bearing is not None:
			available.append("%.0f°" % (self.bearing))
		if self.position_fractional is not None:
			available.append(self.position_fractional)

		if len(available) == 0:
			available.append("no fix")
		return "GPSData(%s)" % (", ".join(available))

class Subtitle(object):
	_Message = collections.namedtuple("Message", [ "gforce_x", "gforce_y", "gforce_z", "gps" ])
	_SEARCH_PLAINTEXT = [ ord(x) for x in "GPRMC" ]
	_CHARDIFF_PLAINTEXT = bytes((a - b) & 0xff for (a, b) in zip(_SEARCH_PLAINTEXT, _SEARCH_PLAINTEXT[1 :]))

	def __init__(self, data, decoding_hint = None):
		assert(isinstance(data, bytes))
		self._data = data
		if len(self) - 1 != self.length_field:
			raise Exception("%d bytes data supplied, but length field was %d (expected %d)." % (len(self), self.length_field, len(self) - 1))
		assert(self._data[2] == 0)

		# Decode message
		chardiff_message = bytes((a - b) & 0xff for (a, b) in zip(self._data[3:], self._data[4:]))
		index = chardiff_message.find(self._CHARDIFF_PLAINTEXT)
		if index == -1:
			# Undecoded
			self._decoded_string = None
			self._decoding_offset = None
		else:
			ciphertext_char = self._data[3 + index]
			plaintext_char = self._SEARCH_PLAINTEXT[0]
			self._decoding_offset = ciphertext_char - plaintext_char
			self._decoded_string = "".join(chr((c - self._decoding_offset) % 256) for c in self._data[3:])

	@property
	def length_field(self):
		return self._decode_uint16(0)

	@property
	def decoding_offset(self):
		return self._decoding_offset

	@property
	def encoded_payload(self):
		return self._data[3:]

	@property
	def decoded_string(self):
		if self._decoded_string is not None:
			return self._decoded_string

	@property
	def decoded_message(self):
		if self._decoded_string is not None:
			s = self.decoded_string.split()
			if len(s) == 4:
				(gx, gy, gz) = (float(value) / 1000 for value in s[0 : 3])
			gps = GPSData(s[3])
			return self._Message(gforce_x = gx, gforce_y = gy, gforce_z = gz, gps = gps)

	def render(self, fmt_string):
		msg = self.decoded_message
		if msg is None:
			available = { }
		else:
			available = {
				"gx":	msg.gforce_x,
				"gy":	msg.gforce_y,
				"gz":	msg.gforce_z,
			}
			if msg.gps.v_gnd_km_h is not None:
				available["v_kmh"] = msg.gps.v_gnd_km_h
			else:
				available["v_kmh"] = 0
		try:
			rendered = fmt_string % available
		except KeyError:
			rendered = ""
		return rendered

	def _decode_uint(self, offset, length):
		return sum(value << (8 * index) for (index, value) in enumerate(reversed(self._data[offset : offset + length])))

	def _decode_uint16(self, offset):
		return self._decode_uint(offset, 2)

	def __len__(self):
		return len(self._data)

	def __repr__(self):
		if self.decoded_string is not None:
			show = self.decoded_string
		else:
			show = self.encoded_payload
		return "SubTitle(len=%d): %s" % (len(self), show)


parser = FriendlyArgumentParser()
parser.add_argument("-r", "--render-string", type = str, default = "%(gx).2f %(gy).2f %(gz).2f %(v_kmh).0f km/h", help = "printf-style format string according to which new subtitles shall be rendered. Defaults to \"%(default)s\". Valid rendering variables are gx, gy, gz, v_kmh.")
parser.add_argument("-v", "--verbose", action = "count", default = 0, help = "Be more verbose during conversion. Can be specified multiple times to increase verbosity.")
parser.add_argument("infile", metavar = "infile", type = str, help = "Dash cam input file.")
parser.add_argument("outfile", metavar = "outfile", type = str, help = "Dash cam output file with custom rendered subtitles.")
args = parser.parse_args(sys.argv[1:])

# Read in subtitles first
stderr_redirect = subprocess.DEVNULL if (args.verbose < 3) else None
subtitle_bindata = subprocess.check_output([ "ffmpeg", "-i", args.infile, "-map", "0:s", "-c", "copy", "-f", "data", "-" ], stderr = stderr_redirect)
subtitle_posdata = subprocess.check_output([ "ffmpeg", "-i", args.infile, "-f", "srt", "-" ], stderr = stderr_redirect)

def seed_to_offset(seed):
	"""This is the experimental determination of the Caesar cipher offset from
	the given seed value. It's not used currently (we use the known-plaintext
	approach because it decodes even subtitles that are sent *before* any seed
	is shown."""
	digits = [ int(char) for char in seed ]
	offset = sum(digits[0 : 8])
	offset += digits[4] + digits[7]
	return offset

# Then parse subtitles first
offset = 0
subtitles = [ ]
seed = None
while offset < len(subtitle_bindata):
	length = (subtitle_bindata[offset] << 8) | (subtitle_bindata[offset + 1] << 0)
	data = subtitle_bindata[offset : offset + length + 1]
	subtitle = Subtitle(data)
	if args.verbose >= 2:
		print(subtitle)
		print("    %s" % (str(subtitle.decoded_message)))
	if subtitle.decoded_message is None:
		encoded = subtitle.encoded_payload.decode("latin1")
		if encoded.isdigit():
			seed = encoded
	else:
		if seed is not None:
			calculated_decoding_offset = seed_to_offset(seed)
			if (args.verbose >= 1) or (calculated_decoding_offset != subtitle.decoding_offset):
				print("Seed = \"%s\", calulated offset = %d, actual offset = %d" % (seed, calculated_decoding_offset, subtitle.decoding_offset))
			seed = None
	subtitles.append(subtitle)
	offset += length + 2

# Afterwards, parse their location and duration
positions = [ ]
for line in subtitle_posdata.decode("utf-8").split("\n"):
	if " --> " in line:
		positions.append(line)

# Then render new subtitles
with tempfile.NamedTemporaryFile("w", suffix = ".srt") as f:
	for (no, (subtitle, position)) in enumerate(zip(subtitles, positions), 1):
		print(no, file = f)
		print(position, file = f)
		print("<font face=\"Arial\" size=\"12\" color=\"#000000\">%s</font>" % (subtitle.render(args.render_string)), file = f)
		print(file = f)
	f.flush()
	subprocess.check_call([ "ffmpeg", "-i", args.infile, "-f", "srt", "-i", f.name, "-map", "0:0", "-map", "0:1", "-map", "1:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-y", args.outfile ], stderr = stderr_redirect)

