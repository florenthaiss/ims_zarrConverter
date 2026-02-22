# IMS -> OME-Zarr v2 Runbook

## Location
- Workspace: `D:\zarrConverterCodex`
- Source IMS: `\yourpathto.ims`
- Output OME-Zarr: `*.zarr`

## Final Files Kept
- `ims_to_omezarr_fast.py`: fast converter (OME-Zarr v2 writer).
- `run_full_ims2zarr_lz4.cmd`: full conversion launcher (recommended settings).
- `open_in_napari.py`: Napari loader with automatic contrast limits.
- `open_tile_000000_ch_639_napari_working.cmd`: one-click Napari launcher.
- `napari311-env`: Python 3.11 environment for Napari compatibility.

## Recommended Conversion Settings
- Workers: `24`
- Chunks: `z=16, y=2048, x=2048`
- Compression: `lz4` with `clevel=1`
- Format: OME-Zarr v2 (`zarr_format=2`)

## Run Conversion
```powershell
\run_full_ims2zarr_lz4.cmd
```

Equivalent direct command:
```powershell
C:\Python314\python.exe ims_to_omezarr_fast.py --input "*.ims" --output "*.ome.zarr" --workers 24 --chunk-z 16 --chunk-y 2048 --chunk-x 2048 --compression lz4 --clevel 1
```

## Open in Napari
Recommended:
```powershell
*_napari_working.cmd
```
This now starts in native 2D mode (level-0 slices) for exact image quality.
You can switch the launcher back to 3D by editing `START_VIEW` in `open_tile_000000_ch_639_napari_working.cmd`.
The launcher uses a stability profile by default:
- `QT_API=pyside6` (forces Qt6 runtime instead of the crashing Qt5 runtime)
- `QT_OPENGL` left on auto for Qt6 (Qt6 no longer supports `angle` value)
- `LOCALAPPDATA=D:\zarrConverterCodex\.napari_localappdata` (isolated local cache/state)
- `NAPARI_CONFIG=D:\zarrConverterCodex\napari_settings_stable.yaml`
- if 3D launch fails, it automatically retries in 2D mode

Default 3D rendering mode is `mip`.
Launcher default 3D pyramid level is `3` (higher resolution than level `4`).
With `--preserve-z` (enabled in the launcher), level `3` means XY decimation target only; Z remains full depth.
You can choose at launch with `--rendering`:
- `attenuated_mip`, `mip`, `translucent`, `iso`, `minip`, `average`, `additive`

Optional plugins are enabled:
- `napari-3d-ortho-viewer`
- `napari-animation`

`napari-ome-zarr` remains enabled for loading OME-Zarr data.

Optional 2D startup:
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr" --view 2d
```

Optional manual 3D level selection:
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr" --view 3d --pyramid-level 2
```

Preserve full Z in 3D while keeping memory bounded:
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr" --view 3d --pyramid-level 3 --preserve-z --max-voxels 300000000
```

Example: force an obvious rendering mode
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr" --view 3d --rendering iso
```

Try full-resolution 3D explicitly (can be unstable/heavy):
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr" --view 3d --pyramid-level 0
```

## Installed Napari Plugins
- `napari-ome-zarr`: OME-Zarr reader.
- `napari-3d-ortho-viewer`: synchronized orthogonal views for 3D volumes.
- `napari-animation`: keyframe/camera animation and movie export.

## Crop OME-Zarr (Z Range)
Use `crop_omezarr_z.py` to crop by Z on level-0 indices.
`--z-start` and `--z-end` are inclusive.

Example used here (`60..770`):
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\crop_omezarr_z.py --input D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr --output D:\zarrConverterCodex\tile_000000_ch_639_z60_770.ome.zarr --z-start 60 --z-end 770 --overwrite
```

## Latest Completed Run (Reference)
- Runtime: `1238.0 s` (`20m 38s`)
- Throughput: `1633.55 MB/s`
- Output size: `~0.5736 TB`
- Log files:
  - `D:\zarrConverterCodex\logs\full_lz4_rerun_stdout_20260216_024741.log`
  - `D:\zarrConverterCodex\logs\full_lz4_rerun_stderr_20260216_024741.log`

## Troubleshooting
- If Napari does not launch, use Python 3.11 env explicitly:
```powershell
D:\zarrConverterCodex\napari311-env\Scripts\python.exe D:\zarrConverterCodex\open_in_napari.py --path "D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr"
```
- If image looks dark/black initially in viewer:
  - adjust contrast limits manually (for this dataset, low values are common),
  - keep gamma near `0.7-1.0`.
