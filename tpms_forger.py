import argparse
import importlib
import os
import re
import shlex
import subprocess
import sys
import time

from colorama import Fore, Style, init
init()

#Output palette:
#	Cyan - labels
#	Dim - hints
#	Magenta - in-progress
#	Green/Red - status
LBL = Fore.CYAN
DIM = Style.DIM
RUN = Fore.MAGENTA + Style.BRIGHT
OK  = Fore.GREEN
ERR = Fore.RED
END = Style.RESET_ALL

#Hardcoded encoder list
#Add new encoders by dropping a file in encoders/ and appending (label, module_name) here
ENCODERS = [
	("Ford", "ford_encoder"),		# [1]
]

#Default HackRF command used when --transmit is given with no quoted argument
#Set to "" to require the user to always supply their own command
HACKRF_DEFAULT_CMD = ""

#Running spinner frames
SPINNER_FRAMES = ["( | )", "( / )", "( - )", "( \\ )"]


def list_encoders():
	print("Available encoders:")
	for i, (label, _) in enumerate(ENCODERS, start=1):
		print(f"  [{i}]\t{label}")


def pop_encoder_index(argv):
	#Pull the encoder selector (e.g. -1, -2) out of argv
	#Argparse cannot parse -1 itself so it reads as a negative number, not a flag
	pattern = re.compile(r"^-(\d+)$")
	cleaned = []
	found   = None
	for tok in argv:
		m = pattern.match(tok)
		if m and found is None:
			found = int(m.group(1))
		else:
			cleaned.append(tok)
	return found, cleaned


def parse_ids(raw):
	#Split comma list, strip whitespace, validate each is 8 hex chars
	ids = [s.strip().lower() for s in raw.split(",") if s.strip()]
	if not ids:
		raise argparse.ArgumentTypeError("--id must contain at least one sensor ID")
	if len(ids) > 4:
		raise argparse.ArgumentTypeError("--id supports up to 4 sensor IDs (one per tire)")
	for sid in ids:
		if len(sid) != 8 or not re.fullmatch(r"[0-9a-f]{8}", sid):
			raise argparse.ArgumentTypeError(f"sensor ID '{sid}' must be exactly 8 hex chars")
	return ids


def transmit(command):
	#Spinner runs in this thread - subprocess streams stdout/stderr away so the line stays clean
	#posix=False on Windows keeps backslash-paths intact
	cmd_args = shlex.split(command, posix=(os.name != "nt"))
	if not cmd_args:
		print(f"{ERR}Error: --transmit command was empty after parsing{END}", file=sys.stderr)
		sys.exit(1)

	print(f"{LBL}Transmitting:{END} {command}")
	print(f"{DIM}Press Ctrl+C to stop.{END}")
	print()

	try:
		proc = subprocess.Popen(cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
	except FileNotFoundError:
		print(f"{ERR}Error: '{cmd_args[0]}' not found on PATH{END}", file=sys.stderr)
		sys.exit(1)

	#Both Python and the child receive Ctrl+C from the shared console
	#The child's signal handler runs hackrf_stop_tx/hackrf_close cleanly
	i		= 0
	stopped	= False
	try:
		while proc.poll() is None:
			sys.stdout.write(f"\r  {RUN}{SPINNER_FRAMES[i % len(SPINNER_FRAMES)]}  Forging RF...{END}")
			sys.stdout.flush()
			i += 1
			time.sleep(0.12)
	except KeyboardInterrupt:
		stopped = True
		try:
			proc.wait(timeout=10)
		except subprocess.TimeoutExpired:
			#Last resort - device may need an unplug-replug
			proc.kill()
			try:
				proc.wait(timeout=2)
			except subprocess.TimeoutExpired:
				pass

	#Clear the spinner line before printing the final status
	sys.stdout.write("\r" + " " * 40 + "\r")

	if stopped:
		print(f"{OK}  ( O )  Stopped.{END}")
	elif proc.returncode == 0:
		print(f"{OK}  ( O )  Done.{END}")
	else:
		#Only surface the subprocess's stderr when something actually went wrong
		err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
		print(f"{ERR}  ( X )  Exited with code {proc.returncode}{END}")
		if err:
			print(f"{ERR}{err}{END}", file=sys.stderr)
		sys.exit(1)


def main():
	enc_index, argv = pop_encoder_index(sys.argv[1:])

	parser = argparse.ArgumentParser(
		prog="tpms_forger",
		description="TPMS packet forger. Builds .cs8 IQ files for replay or HackRF transmission.",
	)
	parser.add_argument("-l", "--list",		action="store_true",								help="list available encoders and exit")
	parser.add_argument("--id",				type=parse_ids,										help="comma-separated sensor IDs")
	parser.add_argument("--pressure",		type=float,											help="tire pressure")
	parser.add_argument("--temperature",	type=float,											help="tire temperature")
	parser.add_argument("--separate",		action="store_true",								help="write a separate pair of .cs8 files per sensor ID")
	parser.add_argument("--transmit",		nargs="?", const="", default=None, metavar="CMD",	help='transmit via HackRF after forging (Ctrl+C to stop) - passes quoted command, or no value to use HACKRF_DEFAULT_CMD')

	args = parser.parse_args(argv)

	if args.list:
		list_encoders()
		return

	if enc_index is None:
		parser.error("no encoder selected. Pass -1, -2, ... (run with -l to list)")
	if enc_index < 1 or enc_index > len(ENCODERS):
		parser.error(f"encoder -{enc_index} out of range (have {len(ENCODERS)} encoders, run with -l to list)")

	if args.id is None:
		parser.error("--id is required")
	if args.pressure is None:
		parser.error("--pressure is required")
	if args.temperature is None:
		parser.error("--temperature is required")

	_, module_name = ENCODERS[enc_index - 1]
	encoder		   = importlib.import_module(f"encoders.{module_name}")

	#Encoders raise ValueError for protocol-specific input issues
	try:
		encoder.forge(args.id, args.pressure, args.temperature, args.separate)
	except ValueError as e:
		print(f"{ERR}Error: {e}{END}", file=sys.stderr)
		sys.exit(1)

	if args.transmit is not None:
		#--transmit was given - "" (the const) means fall back to HACKRF_DEFAULT_CMD
		command = args.transmit.strip() or HACKRF_DEFAULT_CMD.strip()
		if not command:
			print(f"{ERR}Error: --transmit was empty and HACKRF_DEFAULT_CMD is empty{END}", file=sys.stderr)
			sys.exit(1)
		print()
		transmit(command)


if __name__ == "__main__":
	main()
