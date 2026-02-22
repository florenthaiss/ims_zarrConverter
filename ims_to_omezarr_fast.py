import argparse
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Tuple

import h5py
import hdf5plugin  # noqa: F401  # Registers HDF5 compression filters (e.g. LZ4)
import numpy as np
import zarr
from numcodecs import Blosc


G_SRC = None
G_DST = None
G_LEVELS = None


@dataclass
class LevelInfo:
    level: int
    src_path: str
    src_shape_zyx: Tuple[int, int, int]
    dst_shape_zyx: Tuple[int, int, int]
    chunk_zyx: Tuple[int, int, int]



def _decode_attr(value) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, np.ndarray):
        if value.dtype.kind in ("S", "U", "O"):
            parts = []
            for item in value.tolist():
                if isinstance(item, (bytes, np.bytes_)):
                    parts.append(item.decode("utf-8", errors="ignore"))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(value.tolist())
    return str(value)



def _parse_int_attr(group, key: str, default: int) -> int:
    try:
        return int(_decode_attr(group.attrs[key]))
    except Exception:
        return default



def _parse_float_attr(group, key: str, default: float) -> float:
    try:
        return float(_decode_attr(group.attrs[key]))
    except Exception:
        return default



def _sorted_resolution_levels(data_set_group) -> List[int]:
    levels = []
    for key in data_set_group.keys():
        if key.startswith("ResolutionLevel "):
            try:
                levels.append(int(key.split(" ")[-1]))
            except ValueError:
                pass
    return sorted(levels)



def _build_level_infos(src_path: str, chunk_zyx: Tuple[int, int, int]) -> Tuple[List[LevelInfo], Dict]:
    with h5py.File(src_path, "r") as f:
        data_set = f["DataSet"]
        dsi_image = f["DataSetInfo"]["Image"]
        dsi_channel0 = f["DataSetInfo"]["Channel 0"] if "Channel 0" in f["DataSetInfo"] else None

        size_x = _parse_int_attr(dsi_image, "X", 0)
        size_y = _parse_int_attr(dsi_image, "Y", 0)
        size_z = _parse_int_attr(dsi_image, "Z", 0)

        ext_min0 = _parse_float_attr(dsi_image, "ExtMin0", 0.0)
        ext_max0 = _parse_float_attr(dsi_image, "ExtMax0", float(size_x))
        ext_min1 = _parse_float_attr(dsi_image, "ExtMin1", 0.0)
        ext_max1 = _parse_float_attr(dsi_image, "ExtMax1", float(size_y))
        ext_min2 = _parse_float_attr(dsi_image, "ExtMin2", 0.0)
        ext_max2 = _parse_float_attr(dsi_image, "ExtMax2", float(size_z))

        unit_raw = _decode_attr(dsi_image.attrs.get("Unit", "micrometer")).strip().lower()
        if unit_raw in ("um", "?m", "?m"):
            unit = "micrometer"
        elif unit_raw:
            unit = unit_raw
        else:
            unit = "micrometer"

        vx = (ext_max0 - ext_min0) / max(size_x, 1)
        vy = (ext_max1 - ext_min1) / max(size_y, 1)
        vz = (ext_max2 - ext_min2) / max(size_z, 1)

        channel_name = "0"
        if dsi_channel0 is not None:
            channel_name = _decode_attr(dsi_channel0.attrs.get("Name", "0")).strip() or "0"

        levels = _sorted_resolution_levels(data_set)
        if not levels:
            raise RuntimeError("No 'ResolutionLevel N' groups found in IMS DataSet")

        # Determine default timepoint/channel keys from first level.
        first_level_group = data_set[f"ResolutionLevel {levels[0]}"]
        timepoint_key = sorted(first_level_group.keys())[0]
        channel_key = sorted(first_level_group[timepoint_key].keys())[0]

        infos: List[LevelInfo] = []
        for lvl in levels:
            rl_group = data_set[f"ResolutionLevel {lvl}"]
            src_ds = rl_group[timepoint_key][channel_key]["Data"]
            src_z, src_y, src_x = [int(v) for v in src_ds.shape]

            # IMS can store padded resolutions. Crop to mathematically expected pyramid sizes.
            exp_x = max(1, math.ceil(size_x / (2 ** lvl)))
            exp_y = max(1, math.ceil(size_y / (2 ** lvl)))
            exp_z = max(1, math.ceil(size_z / (2 ** lvl)))

            dst_x = min(src_x, exp_x)
            dst_y = min(src_y, exp_y)
            dst_z = min(src_z, exp_z)

            infos.append(
                LevelInfo(
                    level=lvl,
                    src_path=f"DataSet/ResolutionLevel {lvl}/{timepoint_key}/{channel_key}/Data",
                    src_shape_zyx=(src_z, src_y, src_x),
                    dst_shape_zyx=(dst_z, dst_y, dst_x),
                    chunk_zyx=(
                        min(chunk_zyx[0], dst_z),
                        min(chunk_zyx[1], dst_y),
                        min(chunk_zyx[2], dst_x),
                    ),
                )
            )

        meta = {
            "size_xyz": [size_x, size_y, size_z],
            "voxel_size_zyx": [vz, vy, vx],
            "unit": unit,
            "channel_name": channel_name,
            "levels": levels,
            "timepoint_key": timepoint_key,
            "channel_key": channel_key,
        }
        return infos, meta



def _create_omezarr_v2(out_path: str, infos: List[LevelInfo], meta: Dict, compression: str, clevel: int) -> None:
    root = zarr.open_group(out_path, mode="w", zarr_format=2)

    compressor = None
    if compression == "lz4":
        compressor = Blosc(cname="lz4", clevel=clevel, shuffle=Blosc.BITSHUFFLE)
    elif compression == "zstd":
        compressor = Blosc(cname="zstd", clevel=clevel, shuffle=Blosc.BITSHUFFLE)

    datasets_meta = []
    vz, vy, vx = meta["voxel_size_zyx"]
    for info in infos:
        z, y, x = info.dst_shape_zyx
        cz, cy, cx = info.chunk_zyx
        root.create_array(
            str(info.level),
            shape=(1, 1, z, y, x),
            chunks=(1, 1, cz, cy, cx),
            dtype=np.uint16,
            compressor=compressor,
            overwrite=True,
            chunk_key_encoding={"name": "v2", "separator": "/"},
            order="C",
        )
        scale = [1.0, 1.0, vz * (2 ** info.level), vy * (2 ** info.level), vx * (2 ** info.level)]
        datasets_meta.append(
            {
                "path": str(info.level),
                "coordinateTransformations": [{"type": "scale", "scale": scale}],
            }
        )

    root.attrs["multiscales"] = [
        {
            "version": "0.4",
            "name": "image",
            "axes": [
                {"name": "t", "type": "time", "unit": "second"},
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": meta["unit"]},
                {"name": "y", "type": "space", "unit": meta["unit"]},
                {"name": "x", "type": "space", "unit": meta["unit"]},
            ],
            "datasets": datasets_meta,
            "type": "local mean",
        }
    ]

    root.attrs["omero"] = {
        "version": "0.4",
        "name": os.path.basename(out_path),
        "channels": [
            {
                "label": meta["channel_name"],
                "color": "FFFFFF",
                "window": {"min": 0, "max": 65535, "start": 0, "end": 65535},
                "active": True,
                "coefficient": 1.0,
                "family": "linear",
                "inverted": False,
            }
        ],
        "rdefs": {"model": "color", "defaultT": 0, "defaultZ": 0},
    }



def _init_worker(src_path: str, out_path: str, infos_dicts: List[Dict]) -> None:
    global G_SRC, G_DST, G_LEVELS
    os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
    G_SRC = h5py.File(src_path, "r")
    G_DST = zarr.open_group(out_path, mode="a", zarr_format=2)
    G_LEVELS = {d["level"]: d for d in infos_dicts}



def _copy_z_slab(task: Tuple[int, int, int]) -> int:
    level, z0, z1 = task
    info = G_LEVELS[level]
    src = G_SRC[info["src_path"]]
    dst = G_DST[str(level)]
    dz, dy, dx = info["dst_shape_zyx"]
    cz, cy, cx = info["chunk_zyx"]

    # Copy one z slab over all y/x blocks.
    for y0 in range(0, dy, cy):
        y1 = min(y0 + cy, dy)
        for x0 in range(0, dx, cx):
            x1 = min(x0 + cx, dx)
            block = src[z0:z1, y0:y1, x0:x1]
            dst[0, 0, z0:z1, y0:y1, x0:x1] = block

    return int((z1 - z0) * dy * dx * np.dtype(np.uint16).itemsize)


def _copy_z_slab_local(
    src_file: h5py.File, dst_group: zarr.Group, level_map: Dict[int, Dict], task: Tuple[int, int, int]
) -> int:
    level, z0, z1 = task
    info = level_map[level]
    src = src_file[info["src_path"]]
    dst = dst_group[str(level)]
    _, dy, dx = info["dst_shape_zyx"]
    _, cy, cx = info["chunk_zyx"]

    for y0 in range(0, dy, cy):
        y1 = min(y0 + cy, dy)
        for x0 in range(0, dx, cx):
            x1 = min(x0 + cx, dx)
            block = src[z0:z1, y0:y1, x0:x1]
            dst[0, 0, z0:z1, y0:y1, x0:x1] = block

    return int((z1 - z0) * dy * dx * np.dtype(np.uint16).itemsize)



def _build_tasks(infos: List[LevelInfo]) -> Tuple[List[Tuple[int, int, int]], int]:
    tasks: List[Tuple[int, int, int]] = []
    total_bytes = 0
    for info in infos:
        z, y, x = info.dst_shape_zyx
        cz, _, _ = info.chunk_zyx
        total_bytes += z * y * x * np.dtype(np.uint16).itemsize
        for z0 in range(0, z, cz):
            z1 = min(z0 + cz, z)
            tasks.append((info.level, z0, z1))
    return tasks, total_bytes



def main() -> None:
    parser = argparse.ArgumentParser(description="Fast parallel IMS to OME-Zarr v2 converter")
    parser.add_argument("--input", required=True, help="Input .ims path")
    parser.add_argument("--output", required=True, help="Output OME-Zarr directory")
    parser.add_argument("--workers", type=int, default=8, help="Number of worker processes")
    parser.add_argument("--chunk-z", type=int, default=16)
    parser.add_argument("--chunk-y", type=int, default=1024)
    parser.add_argument("--chunk-x", type=int, default=1024)
    parser.add_argument("--compression", choices=["none", "lz4", "zstd"], default="none")
    parser.add_argument("--clevel", type=int, default=1)
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=0,
        help="Benchmark mode: only process the first N z-slab tasks (0 = all tasks).",
    )
    args = parser.parse_args()

    t0 = time.time()
    chunk_zyx = (args.chunk_z, args.chunk_y, args.chunk_x)

    infos, meta = _build_level_infos(args.input, chunk_zyx)
    _create_omezarr_v2(
        args.output,
        infos,
        meta,
        compression=("none" if args.compression == "none" else args.compression),
        clevel=args.clevel,
    )

    tasks, total_bytes = _build_tasks(infos)
    if args.max_tasks and args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]
        if not tasks:
            raise RuntimeError(f"--max-tasks={args.max_tasks} selected no tasks")
        info_by_level = {i.level: i for i in infos}
        total_bytes = sum(
            (z1 - z0) * info_by_level[level].dst_shape_zyx[1] * info_by_level[level].dst_shape_zyx[2] * np.dtype(np.uint16).itemsize
            for (level, z0, z1) in tasks
        )
    infos_dicts = [
        {
            "level": i.level,
            "src_path": i.src_path,
            "dst_shape_zyx": i.dst_shape_zyx,
            "chunk_zyx": i.chunk_zyx,
        }
        for i in infos
    ]

    bytes_done = 0
    last_report = time.time()

    if args.workers <= 1:
        with h5py.File(args.input, "r") as src_file:
            dst_group = zarr.open_group(args.output, mode="a", zarr_format=2)
            level_map = {d["level"]: d for d in infos_dicts}
            for idx, task in enumerate(tasks, 1):
                bytes_done += _copy_z_slab_local(src_file, dst_group, level_map, task)
                now = time.time()
                if now - last_report >= 10 or idx == len(tasks):
                    dt = max(now - t0, 1e-6)
                    mbps = (bytes_done / 1_048_576.0) / dt
                    pct = 100.0 * bytes_done / max(total_bytes, 1)
                    print(
                        f"progress={pct:.3f}% bytes_done={bytes_done} total_bytes={total_bytes} mbps={mbps:.2f} tasks={idx}/{len(tasks)}",
                        flush=True,
                    )
                    last_report = now
    else:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker, initargs=(args.input, args.output, infos_dicts)) as ex:
            futures = [ex.submit(_copy_z_slab, task) for task in tasks]
            for idx, fut in enumerate(as_completed(futures), 1):
                bytes_done += fut.result()
                now = time.time()
                if now - last_report >= 10 or idx == len(futures):
                    dt = max(now - t0, 1e-6)
                    mbps = (bytes_done / 1_048_576.0) / dt
                    pct = 100.0 * bytes_done / max(total_bytes, 1)
                    print(
                        f"progress={pct:.3f}% bytes_done={bytes_done} total_bytes={total_bytes} mbps={mbps:.2f} tasks={idx}/{len(futures)}",
                        flush=True,
                    )
                    last_report = now

    elapsed = time.time() - t0
    mbps = (bytes_done / 1_048_576.0) / max(elapsed, 1e-6)

    stats = {
        "input": args.input,
        "output": args.output,
        "workers": args.workers,
        "chunk_zyx": [args.chunk_z, args.chunk_y, args.chunk_x],
        "max_tasks": args.max_tasks,
        "compression": args.compression,
        "elapsed_seconds": elapsed,
        "bytes_copied": bytes_done,
        "throughput_MBps": mbps,
        "levels": [
            {
                "level": i.level,
                "src_shape_zyx": list(i.src_shape_zyx),
                "dst_shape_zyx": list(i.dst_shape_zyx),
                "chunk_zyx": list(i.chunk_zyx),
            }
            for i in infos
        ],
        "meta": meta,
    }

    with open(os.path.join(args.output, "conversion_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)

    print(f"DONE elapsed={elapsed:.1f}s throughput_MBps={mbps:.2f}")


if __name__ == "__main__":
    main()
