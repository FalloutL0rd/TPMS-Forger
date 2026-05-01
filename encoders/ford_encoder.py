import os
import numpy as np

from colorama import Fore, Style, init
init()

#Output palette:
#	Cyan - labels
#	Yellow - IDs
#	Dim - parentheticals
LBL = Fore.CYAN
SID = Fore.YELLOW + Style.BRIGHT
DIM = Style.DIM
END = Style.RESET_ALL

NAME    = "Ford"
OUT_DIR = "generated_rf"	#All .cs8 files land here relative to the cwd

BAUD_RATE	= 19230
FREQ_DEV	= 33000
REPEAT		= 8				#Bursts per flag variant (doubled overall since we send 2 variants for moving and parked)
GAP_SECONDS	= 0.012

#Flag bytes - rtl_433 tpms_ford.c uses (b[6] & 0x4c) to read state
#	0x44 = moving=1
#	0x08 = learn=1
#	lower two bits 0x03 are unknown_3 status
FLAGS_MOVING = 0x46			#Confirmed working (moving=1, unknown_3=0x02)
FLAGS_PARKED = 0x02			#0x46 with the 0x44 moving bits cleared


def build_payload(sensor_id_hex, pressure_psi, temp_c, flags):
	sid	  = bytes.fromhex(sensor_id_hex)
	if len(sid) != 4:
		raise ValueError("sensor_id_hex must be 8 hex chars")
	raw_p = round(pressure_psi * 4)
	raw_t = round(temp_c + 56)
	body  = bytes([*sid, raw_p, raw_t, flags])
	chk   = sum(body) & 0xFF
	return body + bytes([chk])


def manchester_encode(data):
	#rtl_433 convention: 0 -> (0,1), 1 -> (1,0)
	bits = []
	for byte in data:
		for i in range(7, -1, -1):
			if (byte >> i) & 1:
				bits += [1, 0]
			else:
				bits += [0, 1]
	return bits


def preamble_bits():
	#55 55 55 56 confirmed working preamble
	raw  = bytes.fromhex("55555556")
	bits = []
	for byte in raw:
		for i in range(7, -1, -1):
			bits.append((byte >> i) & 1)
	return bits


def fsk_modulate(bits, sample_rate):
	sps   = int(sample_rate / BAUD_RATE)
	phase = 0.0
	out   = []
	for bit in bits:
		f   = FREQ_DEV if bit else -FREQ_DEV
		inc = 2.0 * np.pi * f / sample_rate
		for _ in range(sps):
			out.append(complex(np.cos(phase), np.sin(phase)))
			phase += inc
	return np.array(out, dtype=np.complex64)


def build_burst(packet, sample_rate):
	#One preamble + manchester FSK burst, no gap, no repeat
	pre  = preamble_bits()
	data = manchester_encode(packet)
	return fsk_modulate(pre + data, sample_rate)


def build_signal(packets, sample_rate):
	#Each packet gets REPEAT bursts back-to-back, gap between bursts and between packets
	gap   = np.zeros(int(sample_rate * GAP_SECONDS), dtype=np.complex64)
	parts = []
	for pkt in packets:
		burst = build_burst(pkt, sample_rate)
		for _ in range(REPEAT):
			parts.append(burst)
			parts.append(gap)
	return np.concatenate(parts)


def write_cs8(signal, filename):
	peak = np.max(np.abs(signal))
	if peak > 0:
		signal = signal / peak
	iq8       = np.empty(len(signal) * 2, dtype=np.int8)
	iq8[0::2] = (signal.real * 120).astype(np.int8)
	iq8[1::2] = (signal.imag * 120).astype(np.int8)
	iq8.tofile(filename)
	print(f"  {DIM}Wrote{END} {filename}  {DIM}({len(iq8) // 1024} KB){END}")


def forge(ids, pressure_psi, temp_c, separate):
	#Ford raw temperature byte = Celsius + 56, so Celsius is the natural input unit
	#Ford protocol gives 1 byte each to pressure and temperature to enforce hard limits up front
	if not (0 <= pressure_psi <= 63.75):
		raise ValueError(f"Pressure {pressure_psi} PSI is outside Ford TPMS range (0 to 63.75 PSI)")
	if not (-56 <= temp_c <= 199):
		raise ValueError(f"Temperature {temp_c} C is outside Ford TPMS range (-56 to 199 C)")

	raw_p = round(pressure_psi * 4)
	raw_t = round(temp_c + 56)

	print(f"{LBL}Encoder      {END}: {NAME}")
	print(f"{LBL}Sensor IDs   {END}: {SID}{', '.join(i.upper() for i in ids)}{END}")
	print(f"{LBL}Pressure     {END}: {pressure_psi} PSI  {DIM}(raw=0x{raw_p:02x}){END}")
	print(f"{LBL}Temperature  {END}: {temp_c} C  {DIM}(raw=0x{raw_t:02x}){END}")
	print(f"{LBL}Flags        {END}: 0x{FLAGS_MOVING:02x} {DIM}(moving){END} + 0x{FLAGS_PARKED:02x} {DIM}(parked){END}")
	print(f"{LBL}Bursts/ID    {END}: {REPEAT} moving + {REPEAT} parked = {REPEAT * 2}")
	print()

	#Build both flag variants per ID so each ID gets two packets
	packets_by_id = {}
	for sid in ids:
		moving = build_payload(sid, pressure_psi, temp_c, FLAGS_MOVING)
		parked = build_payload(sid, pressure_psi, temp_c, FLAGS_PARKED)
		packets_by_id[sid] = [moving, parked]
		print(f"  {SID}{sid.upper()}{END}  {DIM}moving={END}{moving.hex()}  {DIM}parked={END}{parked.hex()}")
	print()

	os.makedirs(OUT_DIR, exist_ok=True)

	if separate:
		#One pair of files per sensor ID: 250k for rtl_433 replay, 2m for HackRF
		for sid, packets in packets_by_id.items():
			sig_250k = build_signal(packets, 250_000)
			sig_2m   = build_signal(packets, 2_000_000)
			write_cs8(sig_250k, os.path.join(OUT_DIR, f"ford_tpms_{sid}_250k.cs8"))
			write_cs8(sig_2m,   os.path.join(OUT_DIR, f"ford_tpms_{sid}_2m.cs8"))
	else:
		#One combined pair containing every ID's packets
		all_packets = [p for packets in packets_by_id.values() for p in packets]
		sig_250k    = build_signal(all_packets, 250_000)
		sig_2m      = build_signal(all_packets, 2_000_000)
		write_cs8(sig_250k, os.path.join(OUT_DIR, "ford_tpms_250k.cs8"))
		write_cs8(sig_2m,   os.path.join(OUT_DIR, "ford_tpms_2m.cs8"))
