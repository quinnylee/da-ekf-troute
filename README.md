# EKF t-route data processing

## Setting up your environment

If you do not yet have astral-uv, please follow the [installation instructions](https://docs.astral.sh/uv/getting-started/installation/) on the uv website.

Clone this repo, `cd` into the repo, and run `uv sync`.

You will also need to [install t-route from scratch](https://github.com/CIROH-UA/t-route#installation). Make sure you install the `EKF_Troute` branch of t-route.

## What is included

Code and data from Quarter 1, Objective 1 (existing linear KF inported directly into t-route as an internal Python libray, baseline simulation results generated), Subtasks 1-4

## How to use

1. Hydrofabric subsetting

    Use the Jupyter notebook in `Q1/O1/1`.

2. T-route forcing generation

    Run these commands:

    ```bash
    cd Q1/O1/2
    python3 troute_forcings.py
    ```

3. Running t-route

    First, the geopackage from step 1 and the lateral inflow files from step 2 are moved or copied into directory `3`.

    Then, t-route is executed using CIROH's t-route Docker image.

    ```bash
    docker run --rm -v "/Users/qylee/Documents/da_ekf_troute/Q1/O1/3:/ngen/ngen/data:rw" -w /ngen/ngen/data --entrypoint python awiciroh/t-route:latest -m nwm_routing -f ./troute.yaml
    ```

    Remember to change the absolute path in the mounted volume to your path!

4. Preprocessing KF input data

    Use `ngen_hf_to_json.ipynb` to convert the geopackage to a KF-compatible models file that uses NextGen IDs.

    Use `usgs_to_ngen_id.ipynb` to convert the USGS-to-COMID file to a USGS-to-wbid file.

5. Running KF with API

    Note: This is a `git clone` of @slama0077's `Python_Interface` repository.

    Run the `interface.ipynb` notebook.
