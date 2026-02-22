@echo off
setlocal

set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"

set "PY=%BASE%\napari311-env\Scripts\python.exe"
set "SCRIPT=%BASE%\open_in_napari.py"
set "CFG=%BASE%\napari_settings_stable.yaml"
set "LOGDIR=%BASE%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "OUTLOG=%LOGDIR%\napari_stdout.log"
set "ERRLOG=%LOGDIR%\napari_stderr.log"
set "NLOCAL=%BASE%\.napari_localappdata"
if not exist "%NLOCAL%" mkdir "%NLOCAL%"
set "LOCALAPPDATA=%NLOCAL%"
set "START_VIEW=2d"
set "RENDERING=mip"
set "PYRAMID_LEVEL=3"
set "PRESERVE_Z=1"
if "%NAPARI_CONFIG%"=="" set "NAPARI_CONFIG=%CFG%"
if "%QT_API%"=="" set "QT_API=pyside6"
if "%QT_OPENGL%"=="" (
  if /I not "%QT_API%"=="pyside6" set "QT_OPENGL=angle"
)

if not "%~1"=="" (
  set "ZARR=%~1"
) else (
  if exist "%BASE%\tile_000000_ch_639.ome.zarr" (
    set "ZARR=%BASE%\tile_000000_ch_639.ome.zarr"
  ) else if exist "%BASE%\tile_000000_ch_639.ome.zarr_fast" (
    set "ZARR=%BASE%\tile_000000_ch_639.ome.zarr_fast"
  ) else (
    echo OME-Zarr folder not found.
    echo Expected one of:
    echo   %BASE%\tile_000000_ch_639.ome.zarr
    echo   %BASE%\tile_000000_ch_639.ome.zarr_fast
    echo.
    echo Or pass a custom path:
    echo   %~nx0 "D:\path\to\dataset.ome.zarr"
    pause
    exit /b 1
  )
)

if not exist "%ZARR%" (
  echo OME-Zarr folder not found: %ZARR%
  pause
  exit /b 1
)

if not exist "%PY%" (
  echo Python not found: %PY%
  pause
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo Script not found: %SCRIPT%
  pause
  exit /b 1
)

echo Opening in Napari:
echo   %ZARR%
echo   LOCALAPPDATA=%LOCALAPPDATA%
echo   NAPARI_CONFIG=%NAPARI_CONFIG%
echo   QT_API=%QT_API%
echo   start_view=%START_VIEW%
if /I "%START_VIEW%"=="3d" (
  echo   rendering=%RENDERING%
  echo   pyramid_level=%PYRAMID_LEVEL%
  echo   preserve_z=%PRESERVE_Z%
)
if "%QT_OPENGL%"=="" (
  echo   QT_OPENGL=(auto)
) else (
  echo   QT_OPENGL=%QT_OPENGL%
)
if /I "%START_VIEW%"=="3d" (
  set "EXTRA_ARGS="
  if "%PRESERVE_Z%"=="1" set "EXTRA_ARGS=--preserve-z"
  "%PY%" -u "%SCRIPT%" --path "%ZARR%" --view 3d --rendering %RENDERING% --pyramid-level %PYRAMID_LEVEL% %EXTRA_ARGS% 1>"%OUTLOG%" 2>"%ERRLOG%"
  if errorlevel 1 (
    echo.
    echo 3D launch failed. Retrying in 2D mode...
    "%PY%" -u "%SCRIPT%" --path "%ZARR%" --view 2d 1>>"%OUTLOG%" 2>>"%ERRLOG%"
    if errorlevel 1 (
      echo.
      echo Napari launch failed.
      pause
      exit /b 1
    )
  )
) else (
  "%PY%" -u "%SCRIPT%" --path "%ZARR%" --view 2d 1>"%OUTLOG%" 2>"%ERRLOG%"
  if errorlevel 1 (
    echo.
    echo Napari launch failed.
    pause
    exit /b 1
  )
)

endlocal
