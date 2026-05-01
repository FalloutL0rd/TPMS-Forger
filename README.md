# tpms_forger

A Python CLI for generating spoofed TPMS (Tire Pressure Monitoring System) sensor packets and transmitting them via HackRF One.

The tool builds protocol-correct packets from user-supplied sensor IDs, pressure, and temperature values, FSK-modulates them at the correct symbol rate, and writes IQ files (`.cs8`) compatible with rtl_433 for offline replay verification and HackRF for over-the-air transmission via an optional `--transmit` flag to launch HackRF directly.

## Ethical use only

> **Read this before running anything that transmits.**
>
> TPMS frequencies (315 MHz in North America, 433 MHz in Europe) are regulated for licensed automotive use. Transmitting on these bands at vehicles you do not own, or in public spaces where signals may reach other drivers, is illegal in most jurisdictions and could compromise vehicle safety systems. Use this tool only:
>
> - Inside a Faraday cage, OR
> - On a vehicle you personally own, OR
> - In a classroom or lab environment with explicit consent of all parties involved.
>
> You are responsible for understanding your local RF spectrum and tampering laws before transmitting. This tool exists for security research and education, not for messing with strangers' cars.

## Equipment

- **HackRF One** for transmit.
- **RTL-SDR** for receive (Optional for testing).
	- Pairs better with rtl_433 to verify forged packets either offline (replay) or live during transmission.

Tested on Windows 11 with PowerShell.
- Linux support is planned.

## How to run it

### Dependencies

- Python 3.8 or newer.
- HackRF tooling: `hackrf_transfer`.
- Optional: [rtl_433](https://github.com/merbanan/rtl_433) for replay verification or live receive.

### Example commands

```PowerShell
#List available encoders
python tpms_forger.py -l

#Forge a single sensor (encoder 1, 31 PSI, 21 C)
python tpms_forger.py -1 --id 12345678 --pressure 31 --temperature 21

#Forge multiple tires into one combined file
python tpms_forger.py -1 --id 12345678,12345679,1234567a,1234567b --pressure 31 --temperature 21

#Same multiple tires, one file per ID
python tpms_forger.py -1 --id 12345678,12345679,1234567a,1234567b --pressure 31 --temperature 21 --separate

#Forge and transmit via HackRF (full hackrf_transfer command in quotes)
python tpms_forger.py -1 --id 12345678 --pressure 31 --temperature 21 --transmit "hackrf_transfer -t generated_rf/<2m_file>.cs8 -f 315000000 -s 2000000 -x 20 -R"

#Replay-decode the 250 kSps file through rtl_433 (no radios needed)
rtl_433 -r generated_rf/<250k_file>.cs8 -s 250000
```

- `--transmit` takes a full shell command in quotes. The script runs it as a subprocess and shows a magenta tire-spinner while it runs. Press Ctrl+C to stop cleanly.
- Substitute `<2m_file>` and `<250k_file>` with the paths the forge step prints; the exact filename depends on which encoder you used.

## Arguments

- `-l`, `--list`: List available encoders and exit.
- `-N` (e.g. `-1`, `-2`): Encoder selector, picking from the order shown by `-l`. Parsed before argparse runs, since argparse reads `-1` as a negative number.
- `--id`: Comma-separated sensor IDs, 8 hex characters each, up to 4 IDs per run.
- `--pressure`: Tire pressure in PSI.
- `--temperature`: Tire temperature. Each encoder declares its own unit; check the encoder source if unsure.
- `--separate`: Write one pair of `.cs8` files per sensor ID instead of one combined pair.
- `--transmit "CMD"`: After forging, run `CMD` as a subprocess and show a status spinner. The full shell command goes inside the quotes. Press Ctrl+C to stop.

## About rtl_433

[rtl_433](https://github.com/merbanan/rtl_433) by [merbanan](https://github.com/merbanan) is the standard open-source tool for receiving and decoding ISM-band sensor protocols (TPMS, weather stations, doorbells, and many others). Encoder logic in this project is reverse-engineered against rtl_433's source. rtl_433 is licensed GPLv2. This project uses it as an external tool (subprocess and replay-file consumer), not as linked code.

### Workflow

This tool produces TPMS packets, rtl_433 verifies them.

1. Forge a packet with `tpms_forger.py`. Two `.cs8` files land in `generated_rf/`: a 250 kSps file for offline replay and a 2 Msps file for HackRF transmission.
2. Replay-decode the 250 kSps file through rtl_433 to confirm the bytes parse correctly.
3. If replay decodes match the input, transmit the 2 Msps file via HackRF.
4. With a separate RTL-SDR running rtl_433 in receive mode, confirm the over-the-air transmission decodes the same as the replay.

If your target vehicle's TPMS has no built-in rtl_433 decoder, rtl_433's flex decoder system (`-X`) lets you describe a custom protocol pattern at the command line for ad-hoc verification.

## Contributing

Contributions are welcome, especially additional vehicle encoders. To add one:

1. Decode the target vehicle's TPMS protocol. Capture real packets with rtl_433, study the bytes, validate against the decoder source.
2. Drop a new file in `encoders/` exposing a `NAME` string and a `forge(ids, pressure_psi, temp, separate)` function. Encoders declare their own input units; the hub passes user input through unchanged.
3. Append `(label, module_name)` to the `ENCODERS` list at the top of `tpms_forger.py`. List order defines the `-N` selector shown by `-l`.
4. Verify end to end with rtl_433 replay decode, then OTA testing in a Faraday cage.

Match the existing color palette (cyan labels, bright yellow IDs, dim parentheticals) so the output stays consistent across encoders.

## License

GPLv3. See `LICENSE` file.

## Credits

- The [rtl_433](https://github.com/merbanan/rtl_433) project for the protocol decoding foundation.
- The 2013 Ford Taurus that survived many TPMS spoofing experiments without complaint.
