import argparse
import os

# Prefer Qt6 at runtime to avoid repeated Qt5Core crashes seen on this machine.
os.environ.setdefault("QT_API", "pyside6")

import numpy as np
import napari

RENDER_MODES = (
    "attenuated_mip",
    "mip",
    "translucent",
    "iso",
    "minip",
    "average",
    "additive",
)


def _count_multiscale_levels(layer_data):
    try:
        n_levels = len(layer_data)
    except TypeError:
        return 0

    if n_levels <= 0:
        return 0

    first = layer_data[0]
    if hasattr(first, "shape"):
        return n_levels
    return 0


def _level_voxels(level_data):
    shape = getattr(level_data, "shape", None)
    if not shape:
        return 0
    vox = 1
    for d in shape:
        vox *= int(d)
    return int(vox)


def _choose_safe_3d_level(layer_data, max_voxels=300_000_000):
    n_levels = _count_multiscale_levels(layer_data)
    if n_levels <= 0:
        return None

    # Find the highest-detail level that stays under the voxel budget.
    for level in range(n_levels):
        try:
            if _level_voxels(layer_data[level]) <= max_voxels:
                return level
        except Exception:
            continue
    return n_levels - 1


def _estimate_xy_decimated_voxels(shape, y_step, x_step):
    if not shape or len(shape) < 2:
        return 0

    vox = 1
    for axis, dim in enumerate(shape):
        d = int(dim)
        if axis == len(shape) - 2:
            d = (d + int(y_step) - 1) // int(y_step)
        elif axis == len(shape) - 1:
            d = (d + int(x_step) - 1) // int(x_step)
        vox *= d
    return int(vox)


def _select_single_scale_level_for_display(viewer, layer, level):
    n_levels = _count_multiscale_levels(layer.data)
    if n_levels <= 0:
        return layer, None, 0

    level = max(0, min(level, n_levels - 1))
    selected = layer.data[level]
    scale = layer.scale
    try:
        # Preserve world scale when extracting a lower-resolution multiscale level.
        factors = np.asarray(layer.downsample_factors[level], dtype=float)
        scale = tuple(np.asarray(layer.scale, dtype=float) * factors)
    except Exception:
        pass

    new_layer = viewer.add_image(
        selected,
        name=layer.name,
        scale=scale,
        translate=layer.translate,
        colormap=layer.colormap,
        opacity=layer.opacity,
        blending=layer.blending,
        visible=layer.visible,
        multiscale=False,
    )
    viewer.layers.remove(layer)
    return new_layer, level, n_levels


def _select_preserve_z_level_for_display(viewer, layer, level, max_voxels=300_000_000):
    n_levels = _count_multiscale_levels(layer.data)
    if n_levels <= 0:
        return layer, None, 0, None

    level = max(0, min(level, n_levels - 1))
    base = layer.data[0]
    base_shape = getattr(base, "shape", None)
    target_shape = getattr(layer.data[level], "shape", None)

    if not base_shape or not target_shape or len(base_shape) < 3:
        fallback, lvl, levels = _select_single_scale_level_for_display(viewer, layer, level)
        return fallback, lvl, levels, None

    y_axis = len(base_shape) - 2
    x_axis = len(base_shape) - 1
    y_factor = max(
        1, int(round(float(base_shape[y_axis]) / max(1.0, float(target_shape[y_axis]))))
    )
    x_factor = max(
        1, int(round(float(base_shape[x_axis]) / max(1.0, float(target_shape[x_axis]))))
    )

    vox = _estimate_xy_decimated_voxels(base_shape, y_factor, x_factor)
    if max_voxels and vox > max_voxels:
        scale_up = (float(vox) / float(max_voxels)) ** 0.5
        y_factor = max(y_factor, int(np.ceil(y_factor * scale_up)))
        x_factor = max(x_factor, int(np.ceil(x_factor * scale_up)))
        while _estimate_xy_decimated_voxels(base_shape, y_factor, x_factor) > max_voxels:
            if y_factor <= x_factor:
                y_factor += 1
            else:
                x_factor += 1

    index = [slice(None)] * len(base_shape)
    index[y_axis] = slice(None, None, y_factor)
    index[x_axis] = slice(None, None, x_factor)
    selected = base[tuple(index)]

    scale = layer.scale
    try:
        scale_arr = np.asarray(layer.scale, dtype=float).copy()
        if scale_arr.size == len(base_shape):
            scale_arr[y_axis] *= float(y_factor)
            scale_arr[x_axis] *= float(x_factor)
            scale = tuple(scale_arr)
    except Exception:
        pass

    new_layer = viewer.add_image(
        selected,
        name=layer.name,
        scale=scale,
        translate=layer.translate,
        colormap=layer.colormap,
        opacity=layer.opacity,
        blending=layer.blending,
        visible=layer.visible,
        multiscale=False,
    )
    viewer.layers.remove(layer)
    return new_layer, level, n_levels, (int(y_factor), int(x_factor))


def _pick_preview_array(layer_data):
    # For multiscale data, use a coarser level for fast percentile estimation.
    n_levels = _count_multiscale_levels(layer_data)
    if n_levels <= 0:
        return layer_data

    return layer_data[min(2, n_levels - 1)]


def _estimate_contrast(arr):
    # Sample sparsely to avoid loading huge volumes into RAM.
    if arr.ndim < 3:
        raise ValueError(f"Expected image data with >=3 dims, got {arr.ndim}")

    # Keep the first index for leading dims (e.g., t/c), subsample spatial z/y/x.
    index = []
    for axis in range(arr.ndim):
        if axis < arr.ndim - 3:
            index.append(0)
        elif axis == arr.ndim - 3:
            index.append(slice(None, None, 16))
        else:
            index.append(slice(None, None, 32))

    sample = arr[tuple(index)]
    if hasattr(sample, "compute"):
        sample = sample.compute()
    sample = np.asarray(sample)
    lo = float(np.percentile(sample, 1.0))
    hi = float(np.percentile(sample, 99.9))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _configure_3d_view(viewer, layer, rendering):
    viewer.dims.ndisplay = 3

    # Prefer volume depiction and attenuated MIP; gracefully fall back if unavailable.
    if hasattr(layer, "depiction"):
        try:
            layer.depiction = "volume"
        except Exception:
            pass

    if hasattr(layer, "rendering"):
        candidates = [rendering] + [m for m in RENDER_MODES if m != rendering]
        for mode in candidates:
            try:
                layer.rendering = mode
                break
            except Exception:
                continue

    if hasattr(layer, "interpolation3d"):
        try:
            layer.interpolation3d = "linear"
        except Exception:
            pass

    if hasattr(layer, "attenuation"):
        try:
            layer.attenuation = 0.05
        except Exception:
            pass

    try:
        viewer.camera.angles = (20.0, 35.0, 110.0)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Open OME-Zarr in Napari with auto contrast.")
    parser.add_argument(
        "--path",
        default=r"D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr",
        help="Path to OME-Zarr root",
    )
    parser.add_argument(
        "--view",
        choices=("3d", "2d"),
        default="3d",
        help="Start in 3D volume view (default) or standard 2D slice view.",
    )
    parser.add_argument(
        "--pyramid-level",
        type=int,
        default=None,
        help="For multiscale inputs in 3D mode, pick pyramid level manually (0=full resolution). Default is auto-safe.",
    )
    parser.add_argument(
        "--preserve-z",
        action="store_true",
        help="Keep full Z depth in 3D and decimate only XY based on selected pyramid level.",
    )
    parser.add_argument(
        "--max-voxels",
        type=int,
        default=300_000_000,
        help="Voxel budget used by --preserve-z when adapting XY decimation.",
    )
    parser.add_argument(
        "--rendering",
        choices=RENDER_MODES,
        default="attenuated_mip",
        help="3D volume rendering mode.",
    )
    args = parser.parse_args()

    path = os.path.abspath(args.path)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"OME-Zarr folder not found: {path}")

    viewer = napari.Viewer(title=f"Napari OME-Zarr: {os.path.basename(path)}")
    layers = viewer.open(path, plugin="napari-ome-zarr")
    if not layers:
        raise RuntimeError(f"No layers loaded from: {path}")

    layer = layers[0]
    chosen_level = None
    xy_steps = None
    n_levels = _count_multiscale_levels(layer.data)
    if args.view == "3d" and n_levels > 0:
        level_to_use = args.pyramid_level
        if level_to_use is None:
            level_to_use = _choose_safe_3d_level(layer.data)
        if args.preserve_z:
            layer, chosen_level, n_levels, xy_steps = _select_preserve_z_level_for_display(
                viewer, layer, level_to_use, max_voxels=args.max_voxels
            )
        else:
            layer, chosen_level, n_levels = _select_single_scale_level_for_display(
                viewer, layer, level_to_use
            )

    preview = _pick_preview_array(layer.data)
    lo, hi = _estimate_contrast(preview)
    layer.contrast_limits = (lo, hi)
    layer.gamma = 0.9

    if args.view == "3d":
        _configure_3d_view(viewer, layer, args.rendering)
        if args.rendering == "iso" and hasattr(layer, "iso_threshold"):
            try:
                layer.iso_threshold = 0.5 * (lo + hi)
            except Exception:
                pass

    print(f"Loaded: {path}")
    print(f"Contrast limits set to: [{lo:.3f}, {hi:.3f}]")
    print(f"View mode: {args.view.upper()}")
    if args.view == "3d" and hasattr(layer, "rendering"):
        try:
            print(f"Rendering: {layer.rendering}")
        except Exception:
            pass
    if chosen_level is not None:
        print(f"Pyramid levels: {n_levels}; using level: {chosen_level}")
    if xy_steps is not None:
        print(f"Preserve-Z XY decimation: y_step={xy_steps[0]}, x_step={xy_steps[1]}")
        try:
            print(f"Displayed array shape: {tuple(int(d) for d in layer.data.shape)}")
        except Exception:
            pass
    napari.run()


if __name__ == "__main__":
    main()
