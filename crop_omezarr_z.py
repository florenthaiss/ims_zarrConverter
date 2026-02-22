import argparse
import copy
import math
import os
import shutil
import time

import zarr


def _find_z_axis(multiscale):
    axes = multiscale.get("axes", [])
    for i, axis in enumerate(axes):
        if str(axis.get("name", "")).lower() == "z":
            return i
    # Typical OME-Zarr order for this dataset is t,c,z,y,x.
    return 2


def _get_scale(dataset_meta, ndim):
    for transform in dataset_meta.get("coordinateTransformations", []):
        if transform.get("type") == "scale":
            scale = transform.get("scale")
            if isinstance(scale, (list, tuple)) and len(scale) == ndim:
                return [float(v) for v in scale]
    return [1.0] * ndim


def _copy_and_crop_level(src_arr, dst_arr, z_axis, src_start, src_stop, slab):
    dst_pos = 0
    n_copied = 0
    for z0 in range(src_start, src_stop, slab):
        z1 = min(z0 + slab, src_stop)
        src_sel = [slice(None)] * src_arr.ndim
        dst_sel = [slice(None)] * src_arr.ndim
        src_sel[z_axis] = slice(z0, z1)
        dst_sel[z_axis] = slice(dst_pos, dst_pos + (z1 - z0))
        dst_arr[tuple(dst_sel)] = src_arr[tuple(src_sel)]
        dst_pos += z1 - z0
        n_copied += z1 - z0
    return n_copied


def main():
    parser = argparse.ArgumentParser(description="Crop an OME-Zarr pyramid in Z only.")
    parser.add_argument("--input", required=True, help="Input OME-Zarr path")
    parser.add_argument("--output", required=True, help="Output OME-Zarr path")
    parser.add_argument("--z-start", type=int, required=True, help="Z start (inclusive, level 0)")
    parser.add_argument("--z-end", type=int, required=True, help="Z end (inclusive, level 0)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists")
    args = parser.parse_args()

    if args.z_start < 0:
        raise ValueError("--z-start must be >= 0")
    if args.z_end < args.z_start:
        raise ValueError("--z-end must be >= --z-start")

    in_path = os.path.abspath(args.input)
    out_path = os.path.abspath(args.output)
    if not os.path.isdir(in_path):
        raise FileNotFoundError(f"Input OME-Zarr directory not found: {in_path}")

    if os.path.exists(out_path):
        if not args.overwrite:
            raise FileExistsError(f"Output already exists: {out_path} (use --overwrite)")
        shutil.rmtree(out_path)

    t0 = time.time()
    src = zarr.open_group(store=in_path, mode="r")
    dst = zarr.open_group(store=out_path, mode="w", zarr_format=2)

    root_attrs = copy.deepcopy(dict(src.attrs))
    multiscales = root_attrs.get("multiscales", [])
    if not multiscales:
        raise RuntimeError("Input is missing multiscales metadata")

    multiscale = multiscales[0]
    z_axis = _find_z_axis(multiscale)
    datasets = multiscale.get("datasets", [])
    if not datasets:
        raise RuntimeError("No multiscale datasets found in metadata")

    # Convert inclusive end to exclusive stop in level-0 coordinates.
    level0_start = int(args.z_start)
    level0_stop = int(args.z_end) + 1

    # Determine level-0 scale so we can map crop indices to each level.
    first_path = str(datasets[0]["path"])
    first_arr = src[first_path]
    level0_scale = _get_scale(datasets[0], first_arr.ndim)

    copied_summary = []
    for ds_meta in datasets:
        path = str(ds_meta["path"])
        src_arr = src[path]
        ndim = src_arr.ndim
        if z_axis >= ndim:
            raise RuntimeError(f"Z axis index {z_axis} out of bounds for dataset {path} with ndim={ndim}")

        level_scale = _get_scale(ds_meta, ndim)
        base_z = level0_scale[z_axis] if level0_scale[z_axis] != 0 else 1.0
        factor = level_scale[z_axis] / base_z
        if factor <= 0:
            factor = 1.0

        level_start = int(math.floor(level0_start / factor))
        level_stop = int(math.ceil(level0_stop / factor))
        level_start = max(0, min(level_start, src_arr.shape[z_axis]))
        level_stop = max(level_start, min(level_stop, src_arr.shape[z_axis]))

        dst_shape = list(src_arr.shape)
        dst_shape[z_axis] = level_stop - level_start
        if dst_shape[z_axis] <= 0:
            raise RuntimeError(f"Crop produced empty Z for level {path}; check requested range")

        src_chunks = src_arr.chunks if src_arr.chunks is not None else src_arr.shape
        dst_chunks = list(src_chunks)
        dst_chunks[z_axis] = min(dst_chunks[z_axis], dst_shape[z_axis])

        dst_arr = dst.create_array(
            path,
            shape=tuple(dst_shape),
            chunks=tuple(dst_chunks),
            dtype=src_arr.dtype,
            compressor=src_arr.compressor,
            filters=src_arr.filters,
            fill_value=src_arr.fill_value,
            order=getattr(src_arr, "order", "C"),
            overwrite=True,
        )

        copied_slices = _copy_and_crop_level(
            src_arr=src_arr,
            dst_arr=dst_arr,
            z_axis=z_axis,
            src_start=level_start,
            src_stop=level_stop,
            slab=max(1, int(src_chunks[z_axis])),
        )

        copied_summary.append(
            {
                "level": path,
                "factor_from_level0": factor,
                "source_z_range": [level_start, level_stop - 1],
                "copied_slices": copied_slices,
                "dst_shape": list(dst_shape),
            }
        )

        print(
            f"level={path} factor={factor:.4g} z={level_start}:{level_stop} "
            f"dst_shape={tuple(dst_shape)}",
            flush=True,
        )

    # Preserve metadata and add crop record.
    if "omero" in root_attrs and isinstance(root_attrs["omero"], dict):
        root_attrs["omero"]["name"] = os.path.basename(out_path)
    root_attrs["crop"] = {
        "source": in_path,
        "z_start_inclusive": int(args.z_start),
        "z_end_inclusive": int(args.z_end),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    for k, v in root_attrs.items():
        dst.attrs[k] = v

    elapsed = time.time() - t0
    print(f"DONE elapsed={elapsed:.1f}s output={out_path}", flush=True)
    print(f"SUMMARY: {copied_summary}", flush=True)


if __name__ == "__main__":
    main()
