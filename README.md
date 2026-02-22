# IMS to OME-Zarr Converter

This repository provides a practical workflow to:
- Convert `.ims` microscopy volumes to OME-Zarr v2.
- Open OME-Zarr in Napari with stable startup defaults and auto-contrast.
- Crop an OME-Zarr volume by a Z range.

The project is Windows-first and uses explicit path-based launch scripts.

## Repository Contents
- `ims_to_omezarr_fast.py`: parallel IMS to OME-Zarr v2 converter.
- `run_full_ims2zarr_lz4.cmd`: one-click conversion launcher (edit paths/settings inside).
- `open_in_napari.py`: OME-Zarr loader for Napari with 2D/3D options.
- `open_tile_000000_ch_639_napari_working.cmd`: one-click Napari launcher.
- `crop_omezarr_z.py`: Z-range cropper for OME-Zarr pyramids.
- `napari_settings_stable.yaml`: Napari config profile used by launcher.

## Path Entries to Adapt
Use these example entries and replace them with your own locations.

```text
REPO_ROOT   = D:\zarrConverterCodex
INPUT_IMS   = H:\exaSPIM_123456_2025-11-28_18-23-50\exaSPIM\tile_000000_ch_639.ims
OUTPUT_ZARR = D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr
PY_CONVERT  = C:\Python314\python.exe
PY_NAPARI   = D:\zarrConverterCodex\napari311-env\Scripts\python.exe
```

If you use the `.cmd` launchers, update path variables at the top of each file:
- `run_full_ims2zarr_lz4.cmd`: `PY`, `SCRIPT`, `INPUT`, `OUTPUT`
- `open_tile_000000_ch_639_napari_working.cmd`: `PY`, `SCRIPT`, fallback `ZARR` path

## Requirements
Minimum Python packages used by scripts:
- `numpy`
- `h5py`
- `hdf5plugin`
- `zarr`
- `numcodecs`
- `napari`
- `napari-ome-zarr`

Example install (single environment):

```powershell
C:\Python314\python.exe -m pip install numpy h5py hdf5plugin zarr numcodecs napari napari-ome-zarr
```

## 1) Convert IMS to OME-Zarr
Recommended command shape:

```powershell
C:\Python314\python.exe D:\zarrConverterCodex\ims_to_omezarr_fast.py --input "H:\path\to\input.ims" --output "D:\path\to\output.ome.zarr" --workers 24 --chunk-z 16 --chunk-y 2048 --chunk-x 2048 --compression lz4 --clevel 1
```

Or run the launcher after editing its variables:

```powershell
D:\zarrConverterCodex\run_full_ims2zarr_lz4.cmd
```

### Important converter options
- `--workers`: process count (set to available CPU budget).
- `--chunk-z --chunk-y --chunk-x`: output chunk size.
- `--compression`: `none`, `lz4`, or `zstd`.
- `--clevel`: compression level for `lz4`/`zstd`.
- `--max-tasks`: benchmark mode (process first N slabs only).

The converter writes `conversion_stats.json` inside output `.ome.zarr`.

## 2) Open OME-Zarr in Napari
Quick start with script defaults:

```powershell
D:\zarrConverterCodex\open_tile_000000_ch_639_napari_working.cmd
```

Direct Python usage:

```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\path\to\dataset.ome.zarr" --view 2d
```

3D example:

```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\path\to\dataset.ome.zarr" --view 3d --rendering attenuated_mip --pyramid-level 3 --preserve-z --max-voxels 300000000
```

### Napari script options
- `--view`: `2d` or `3d`
- `--pyramid-level`: choose multiscale level (`0` = full resolution)
- `--preserve-z`: keep full Z, decimate XY only
- `--max-voxels`: XY decimation budget used with `--preserve-z`
- `--rendering`: 3D rendering mode

## 3) Crop OME-Zarr by Z range
`--z-start` and `--z-end` are inclusive level-0 indices.

```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\crop_omezarr_z.py --input "D:\path\to\input.ome.zarr" --output "D:\path\to\output_crop.ome.zarr" --z-start 60 --z-end 770 --overwrite
```

## Troubleshooting
- If a launcher fails, run the corresponding Python command directly to see full errors.
- If Napari appears black/dim initially, adjust contrast limits and gamma.
- If path errors occur, verify all configured entries are absolute Windows paths.
