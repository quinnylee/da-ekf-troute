# EKF t-route data processing

## Setting up your environment

If you do not yet have astral-uv, please follow the [installation instructions](https://docs.astral.sh/uv/getting-started/installation/) on the uv website.

Clone this rep, `cd` into the repo, and run `uv sync`.

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
