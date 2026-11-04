from pathlib import Path
import numpy as np
import xarray as xr

gages = [
    "08072700",
    "08075900",
    "08076700",
    "08076000",
    "08073600",
    "08075000",
    "08074760",
    "08074800",
    "08075763",
    "08075400",
    "08075780",
    "08076500",
    "08074250",
    "08074150",
    "08075500",
    "08074540",
    "08074000",
    "08073700",
    "08075770",
    "08076180",
    "08069500",
    "08073500",
    "08072730",
    "08072300",
    "08074500",
    "08072760",
    "08075730",
    "08071500",
]
gage_set = set(gages)

in_dir = Path("/Users/qylee/Documents/da_ekf_troute/Q1/O1/2/usgs_timeslices")
out_dir = Path("/Users/qylee/Documents/da_ekf_troute/Q1/O1/2/trimmed_usgs_timeslices")
out_dir.mkdir(parents=True, exist_ok=True)

found = set()

for f in sorted(in_dir.glob("*.usgsTimeSlice.ncdf")):
    with xr.open_dataset(f, decode_times=False, decode_timedelta=False) as ds:
        ids = np.char.strip(ds["stationId"].values.astype(str))
        mask = np.isin(ids, list(gage_set))
        found.update(ids[mask])

        sub = ds.isel(stationIdInd=np.flatnonzero(mask)).load()
        sub.attrs = ds.attrs  # keep fileUpdateTimeUTC, sliceCenterTimeUTC, etc.

    sub.to_netcdf(out_dir / f.name)
    print(f"{f.name}: kept {mask.sum()} / {len(mask)}")

print("Gages never found in any file:", sorted(gage_set - found))
