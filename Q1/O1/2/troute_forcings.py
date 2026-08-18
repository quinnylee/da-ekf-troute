"""
Get t-route forcings from NWM retrospective 3.0. Code and workflow from forcingprocessor
https://github.com/CIROH-UA/forcingprocessor.git

Written by Quinn Russell
Source repo by Jordan Laser
"""

import json
import os
import itertools
from io import BytesIO
from pathlib import Path
from datetime import datetime
import concurrent.futures as cf
from typing import Tuple

import requests
import nwmurl
import geopandas as gpd
import xarray as xr
import numpy as np
import pandas as pd

# Useful tools from forcingprocessor

B2MB = 1048576

def write_netcdf_chrt(
    prefix: Path, data: np.ndarray, times: list, name: str
) -> None:
    """
    Write channel routing data to a NetCDF file.

    Parameters:
        prefix (Path): filename prefix
        data (numpy.ndarray): 2D array with dimensions (nexus-id, qlateral).
        times (list): list representing time axis.
        name (str): string for the filename
    """

    nc_filename = Path(prefix, name)

    time_coord = pd.to_datetime(times)
    feature_ids = data[0, :, 0]
    q_lateral = data[:, :, 1].astype(float)

    ds = xr.Dataset(
        {"q_lateral": (("time", "feature_id"), q_lateral)},
        coords={"time": time_coord, "feature_id": feature_ids},
    )

    ds.to_netcdf(nc_filename, engine="netcdf4")
    print(f"netcdf has been written to {nc_filename}")


def distribute_work(items, nprocs_arg):
    """
    Distribute items evenly between processes, round robin
    """
    items_per_proc = [0 for x in range(nprocs_arg)]
    for j in range(len(items)):
        k = j % nprocs_arg
        items_per_proc[k] = items_per_proc[k] + 1
    return items_per_proc


def load_balance(items_per_proc, launch_delay, single_ex, exec_count):
    """
    Python takes a couple seconds to launch a process so if this script is launched with 10's
    of processes, it may not be optimal to distribute the work evenly.
    This function minimizes projected processing time

    items_per_proc : list of length number of processes with each element representing the number of
        items the process has been assigned
    launch_delay   : time in seconds it takes python to launch the function
    single_ex      : time in seconds it takes to process 1 item
    exec_count     : number of items processed per execution

    """
    nprocs_temp = len(items_per_proc)
    completion_time = [
        single_ex * x / exec_count + launch_delay * j
        for j, x in enumerate(items_per_proc)
    ]
    while True:
        if len(np.nonzero(items_per_proc)[0]) > 0:
            break
        max_time = max(completion_time)
        max_loc = completion_time.index(max_time)
        min_time = min(completion_time)
        min_loc = completion_time.index(min_time)
        if max_time - min_time > single_ex:
            items_per_proc[max_loc] -= 1
            items_per_proc[min_loc] += 1
        else:
            break
        completion_time = [
            single_ex * x / exec_count + launch_delay * j
            for j, x in enumerate(items_per_proc)
        ]

    completion_time = [
        single_ex * x / exec_count + j for j, x in enumerate(items_per_proc)
    ]
    ntasked = len(np.nonzero(items_per_proc)[0])
    if nprocs_temp > ntasked:
        nprocs_temp = ntasked
        completion_time = completion_time[:ntasked]
        items_per_proc = items_per_proc[:ntasked]
    return items_per_proc


def multiprocess_chrt_extract(
        files: list,
        num_procs: int,
        mapping: dict
    ) -> Tuple[np.ndarray, list]:
    """
    Sets up the multiprocessing pool for forcing_grid2catchment and returns the data and time axis
    ordered in time.

    Parameters:
        files (list): List of files to be processed.
        nprocs (int): Number of processes to be used.
        mapping (dict): Dictionary that maps NWM IDs to NGEN IDs.

    Returns:
        data_array (numpy.ndarray): Concatenated array containing the extracted data.
        t_ax_local (list): List of time axes corresponding to the extracted data.
    """
    launch_time = 0.05
    cycle_time = 35
    files_per_cycle = 1
    files_per_proc = distribute_work(files, num_procs)
    files_per_proc = load_balance(
        files_per_proc, launch_time, cycle_time, files_per_cycle
    )
    num_procs = len(files_per_proc)

    start = 0
    nfiles = len(files)
    files_list = []
    for i in range(num_procs):
        end = min(start + files_per_proc[i], nfiles)
        files_list.append(files[start:end])
        start = end

    data_ax = []
    t_ax_local = []
    with cf.ProcessPoolExecutor(max_workers=num_procs) as pool:
        for results in pool.map(
            channelrouting_nwm2ngen,
            files_list,
            [mapping for x in range(num_procs)],
        ):
            data_ax.append(results[0])
            t_ax_local.append(results[1])

    print("Processes have returned")
    data_array_temp = np.concatenate(data_ax)
    data_array_mp = data_array_temp.copy().astype(object)
    data_array_mp[:, :, 1] = data_array_mp[:, :, 1].astype(float)

    t_ax_local = [item for sublist in t_ax_local for item in sublist]

    return data_array_mp, t_ax_local

def write_df(
    df: pd.DataFrame,
    filename: str,
    local_path: str | None = None,
):
    """
    Write a DataFrame to S3 or local storage as a CSV or Parquet file.
    The file type is inferred from the filename extension.

    Args:
        df (pd.DataFrame): DataFrame to write.
        filename (str): Name of the file (e.g., 'metadata.csv' or 'metadata.parquet').
        local_path (str, optional): Local directory path.
    """

    if local_path is None:
        local_path = "."

    out_path = Path(local_path, filename)
    df.to_csv(out_path, header=False)


def write_data_df(
    data,
    t_ax_arg,
    catchments_arg,
    out_path,
    data_source_arg,
) -> Tuple[list, list]:
    """
    Write catchment forcing data to csv or parquet if requested. Also responsible for
    creating/formatting data in memory for tar writing and metadata collection.

    Args:
        data: Input data to be written (numpy array)
        t_ax_arg: Time axis data (numpy array)
        catchments_arg: List of catchment identifiers
        out_path: Output path for writing files
        ii_print: Flag for printing progress information

    Returns:
        forcing_cat_ids: List of catchment identifiers
        filenames: List of filenames
    """

    forcing_cat_ids = []
    filenames = []
    filename = ""

    for j, jcatch in enumerate(catchments_arg):
        df_data = data[:, j, :]
        try:
            df = pd.DataFrame(df_data, columns=["feature_id", "q_lateral"])
        except:
            print("data source", data_source_arg)
            raise
        df = df[["q_lateral"]]
        df["time"] = t_ax_arg
        df = df[["time", "q_lateral"]]  # reorder cols to maintain parity

        nex_id = jcatch

        filename = f"{nex_id}.csv"
        kwargs = {"local_path": out_path}
        write_df(df, filename, **kwargs)

        filenames.append(str(Path(filename).name))

        if j == 0:
            if not os.path.exists(filename):
                filename = f"./{nex_id}.csv"
                df.to_csv(filename, index=False)
                os.remove(filename)

    return forcing_cat_ids, filenames

def channelrouting_nwm2ngen(
    nwm_files: list,
    mapping_arg: dict,
) -> list[list]:
    """
    Retrieve catchment level data from national water model files

    Inputs:
    nwm_files (list): list of filenames (urls for remote, local paths otherwise),
    fs_arg (filesystem): an optional file system for cloud storage reads

    Outputs: [data_list, t_list, nwm_file_sizes_MB]
    data_list (list): list of ngen forcings ordered in time.
    t_list (list): list of model output times
    """
    t_list = []
    nwm_cats = list(itertools.chain.from_iterable(list(mapping_arg.values())))

    data_list = []

    for _, nwm_file in enumerate(nwm_files):
        response = requests.get(nwm_file, timeout=10)

        if response.status_code == 200:
            file_obj = BytesIO(response.content)
        else:
            raise RuntimeError(f"{nwm_file} does not exist")

        with xr.open_dataset(file_obj, chunks={}) as nwm_data:
            data_allnwm = {}
            try:
                subset = nwm_data.sel(feature_id=nwm_cats)
                valid_nwm_cats = nwm_cats
            except KeyError:
                print(
                    f"Some NWM IDs from the mapping are not present in {nwm_file}. Only "
                    + "processing available IDs.",
                    flush=True,
                )
                feature_ids_in_file = set(nwm_data["feature_id"].values)
                valid_nwm_cats = feature_ids_in_file.intersection(nwm_cats)
                subset = nwm_data.sel(feature_id=list(valid_nwm_cats))

            data_allnwm = dict(
                zip(subset["feature_id"].values, subset["q_lateral"].values)
            )
            t = datetime.strftime(
                datetime.strptime(
                    nwm_file.split("/")[-1].split(".")[0], "%Y%m%d%H%M"
                ),
                "%Y-%m-%d %H:%M:%S",
            )
            t_list.append(t)
        del nwm_data, subset
        data_allngen = {}
        valid_nwm_set = set(valid_nwm_cats)
        for ngen_nex, nwm_ids in mapping_arg.items():
            data_allngen[ngen_nex] = sum(
                data_allnwm[nwm_id] for nwm_id in nwm_ids if nwm_id in valid_nwm_set
            )
        data_array_per_file = np.array(list(data_allngen.items()))

        data_list.append(data_array_per_file)

    return [data_list, t_list]

def multiprocess_write_df(data, t_ax_arg, catchments_arg, nprocs_arg, out_path, data_source_type):
    """
    Sets up the process pool for write_data_df.

    Parameters:
        data (numpy.ndarray): 3D array containing the data to be written.
        t_ax_arg (numpy.ndarray): Array representing the time axis of the data.
        catchment_args (iterable): List of catchment identifiers.
        nprocs (int): Number of processes to be used for writing data.
        out_path (str): Path where the output files will be saved.
        data_source_type (str): channel_routing or forcings
    """

    launch_time = 0.05
    cycle_time = 1
    catchments_per_cycle = 200
    catchments_per_proc = distribute_work(catchments_arg, nprocs_arg)
    catchments_per_proc = load_balance(
        catchments_per_proc, launch_time, cycle_time, catchments_per_cycle
    )

    ncatchments = len(catchments_arg)
    out_path_list = []
    worker_time_list = []
    worker_data_list = []
    worker_catchment_list = []
    worker_catchments = {}

    i = 0
    count = 0
    start = 0
    end = 0
    for j, jcatch in enumerate(catchments_arg):
        worker_catchments[jcatch] = jcatch
        count += 1
        if count == catchments_per_proc[i] or j == ncatchments - 1:

            end = min(start + catchments_per_proc[i], ncatchments)
            if data_source_type == "forcings":
                worker_data = data[:, :, start:end]
            else:
                worker_data = data[:, start:end, :]
            worker_data_list.append(worker_data)
            start = end

            worker_catchment_list.append(worker_catchments)
            out_path_list.append(out_path)
            worker_time_list.append(t_ax_arg)

            worker_catchments = {}
            count = 0

            i += 1

    ids = []
    filenames = []
    with cf.ProcessPoolExecutor(max_workers=nprocs_arg) as pool:
        for results in pool.map(
            write_data_df,
            worker_data_list,
            worker_time_list,
            worker_catchment_list,
            out_path_list,
            [data_source_type for x in range(nprocs_arg)],
        ):
            ids.append(results[0])
            filenames.append(results[1])
    print("\n\nGathering data from write processes...")

def main():
    """Get NWM retro data, convert it to t-route ingestible format
    """
    # run nwmurl
    start_date = "202208220000"
    end_date = "202208240000"
    urlbaseinput = 4
    selected_var_types = [1]
    selected_object_types = [2]
    write_to_file = True

    _ = nwmurl.generate_urls_retro(
        start_date,
        end_date,
        urlbaseinput,
        selected_object_types,
        selected_var_types,
        write_to_file
    )

    # read nwmurl list
    nwm_forcing_files = []
    with open("retro_filenamelist.txt", "r", encoding="utf-8") as fp:
        for jline in fp.readlines():
            nwm_forcing_files.append(jline.strip())

    # Open map file and subsetted gpkg
    with open("nwm_to_ngen_map.json", "r", encoding="utf-8") as map_file:
        full_nwm_ngen_map = json.load(map_file)

    gpkg = gpd.read_file("../1/tx_subset.gpkg", layer="nexus")
    catchments = gpkg["id"].to_list()
    nwm_ngen_map = {}
    for catch in catchments:
        if "tnx" not in catch and "cnx" not in catch and "inx" not in catch:
            nwm_ngen_map[catch] = full_nwm_ngen_map[catch]

    cpu_count = os.cpu_count()
    if cpu_count is None:
        cpu_count = 1

    nprocs = int(cpu_count* 0.5)

    data_array, t_ax = multiprocess_chrt_extract(
        nwm_forcing_files, nprocs, nwm_ngen_map
    )

    forcing_path = "./lateral_inflow"

    multiprocess_write_df(
        data_array,
        t_ax,
        list(nwm_ngen_map.keys()),
        nprocs,
        out_path=forcing_path,
        data_source_type="channel_routing",
    )

if __name__ == "__main__":
    main()
