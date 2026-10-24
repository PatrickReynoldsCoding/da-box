# USB drive samples

Each file is one kind of drive: `lsblk` output, the udev properties of each device, and what the
box must do with it (`expect`). `tests/test_usb_drives.py` runs every file. `source` says whether
the sample was recorded on a real machine (`real: ...`) or written from known output (`typical`).

## Record a real drive

On the box, with the drive plugged in:

```sh
lsblk -J -o PATH,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN,PKNAME
udevadm info -q property -n /dev/sdX1    # for each partition
```

Put them in a new file (copy one of these as a start), set `source` to `real: <machine>, <date>`,
and fill in `expect`. A typical sample of the same kind can then go.
