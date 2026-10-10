#!/usr/bin/env bash
# camera_lock.sh - lock the Brio 101's exposure and white balance so panorama seams match.
# Works on the host or inside the container (both have v4l2-ctl).
#
#   camera_lock.sh                    freeze whatever auto mode has currently settled on
#   camera_lock.sh EXPOSURE GAIN WB   set explicit values (e.g. 300 130 5000)
#   camera_lock.sh --auto             back to auto exposure + auto white balance
#
# Ranges: exposure 5-2500 (x100 us, so 333 = 33 ms), gain 0-255, white balance 2800-7500 K.
# Tip: point the camera at a typical part of the habitat, wait ~2 s, then run with no arguments.
#
# WHEN TO RUN: see the note at the bottom of this file.

DEV=/dev/v4l/by-id/usb-046d_Brio_101_2444APDA1MB8-video-index0
get() { v4l2-ctl -d "$DEV" --get-ctrl "$1" | awk '{print $2}'; }
show() { v4l2-ctl -d "$DEV" --get-ctrl auto_exposure,exposure_time_absolute,gain,white_balance_automatic,white_balance_temperature,exposure_dynamic_framerate; }

if [ "$1" = "--auto" ]; then
  v4l2-ctl -d "$DEV" --set-ctrl auto_exposure=3,white_balance_automatic=1,exposure_dynamic_framerate=1
  echo "Auto exposure + auto white balance restored:"; show
  exit 0
fi

# read the auto-converged values BEFORE switching to manual
EXPOSURE=${1:-$(get exposure_time_absolute)}
GAIN=${2:-$(get gain)}
WB=${3:-$(get white_balance_temperature)}

# manual mode first (the value controls are inactive while auto is on), then the values
v4l2-ctl -d "$DEV" --set-ctrl auto_exposure=1,white_balance_automatic=0,exposure_dynamic_framerate=0 || exit 1
v4l2-ctl -d "$DEV" --set-ctrl exposure_time_absolute="$EXPOSURE",gain="$GAIN",white_balance_temperature="$WB" || exit 1
echo "Locked (exposure=$EXPOSURE gain=$GAIN white_balance=$WB). Camera now reports:"; show

# WHEN TO RUN (tested 2026-10-10 on the Pi, Brio 101 + usb_cam):
#   - Works both BEFORE and AFTER usb_cam starts. The lock survived a usb_cam restart:
#     usb_cam tries to re-enable auto using old control names ('exposure_auto',
#     'white_balance_temperature_auto') that this camera doesn't have, so it changes nothing.
#   - Recommended: run it AFTER bringup with the camera looking at the scene, so the
#     no-argument form freezes sensible values. Freezing with the stream stopped just
#     re-uses whatever the camera last had.
#   - Not tested: unplugging the camera or rebooting the Pi. Assume that resets it to auto; re-run.
#   - usb_cam does set 'brightness' on every start (the launch file pins it to 128, the camera default).
