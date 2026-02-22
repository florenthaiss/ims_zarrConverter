@echo off
setlocal
set "PY=C:\Python314\python.exe"
set "SCRIPT=D:\zarrConverterCodex\ims_to_omezarr_fast.py"
set "INPUT=H:\exaSPIM_123456_2025-11-28_18-23-50\exaSPIM\tile_000000_ch_639.ims"
set "OUTPUT=D:\zarrConverterCodex\tile_000000_ch_639.ome.zarr"

"%PY%" "%SCRIPT%" ^
  --input "%INPUT%" ^
  --output "%OUTPUT%" ^
  --workers 24 ^
  --chunk-z 16 ^
  --chunk-y 2048 ^
  --chunk-x 2048 ^
  --compression lz4 ^
  --clevel 1

endlocal
