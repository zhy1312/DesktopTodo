# Multi-monitor regression test (ASCII only)
# Layout on this machine (physical px):
#   primary:   (0, 0)      2560x1440  work area bottom = 1380
#   secondary: (2560,-493) 1440x2560 (portrait, right side)
# Steps:
#   S2 drag to secondary center   -> window must land on 2nd screen
#   S3 drag to junction (x=2560)  -> must NOT collapse, must NOT jump screens
#   S4 drag to secondary right    -> must collapse to 8px strip
#   S5 hover strip                -> must expand back to ORIGINAL position on secondary
#   S6 mouse away                 -> must re-collapse
#   S7 drag to primary left edge  -> collapse
#   S8 hover strip                -> must expand back on PRIMARY (no screen jump)
#   S9 drag into bottom dead zone -> must be clamped into primary work area
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System.Runtime.InteropServices;
public class DpiHelper { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[DpiHelper]::SetProcessDPIAware() | Out-Null

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(int f, int dx, int dy, int data, IntPtr extra);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

function Get-AppRect {
  $found = $null
  foreach ($x in @(Get-Process DesktopTodo -ErrorAction SilentlyContinue)) {
    if ($x.MainWindowHandle -ne [IntPtr]::Zero) { $found = $x; break }
  }
  if (-not $found) { return $null }
  $r = New-Object Win+RECT
  [Win]::GetWindowRect($found.MainWindowHandle, [ref]$r) | Out-Null
  return @{L=$r.Left; T=$r.Top; R=$r.Right; B=$r.Bottom; H=$found.MainWindowHandle}
}

function Shot([int]$x, [int]$y, [int]$w, [int]$h, $path) {
  if ($w -lt 1) { $w = 1 }
  if ($h -lt 1) { $h = 1 }
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
}

function DragTo([int]$x0, [int]$y0, [int]$x1, [int]$y1) {
  [Win]::SetCursorPos($x0, $y0) | Out-Null
  Start-Sleep -Milliseconds 150
  [Win]::mouse_event(2, $x0, $y0, 0, [IntPtr]::Zero)
  for ($i = 1; $i -le 15; $i++) {
    $x = [int]($x0 + ($x1 - $x0) * $i / 15)
    $y = [int]($y0 + ($y1 - $y0) * $i / 15)
    [Win]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 20
  }
  [Win]::mouse_event(4, $x1, $y1, 0, [IntPtr]::Zero)
}

# drag the window so its top-left lands at (winL, winT): grab offset = (0.35*W, 18)
function DragWindow([int]$winL, [int]$winT) {
  $r = Get-AppRect
  if (-not $r) { throw "FAIL: window not found during drag" }
  $ox = [int](0.35 * ($r.R - $r.L))
  DragTo ($r.L + $ox) ($r.T + 18) ($winL + $ox) ($winT + 18)
}

$shots = "C:\Users\13124\WorkBuddy\2026-10-14-09-54-23\desktop-todo\shots"
New-Item -ItemType Directory -Force -Path $shots | Out-Null

$exe = "C:\Users\13124\WorkBuddy\2026-10-14-09-54-23\desktop-todo\dist\DesktopTodo.exe"
Start-Process -FilePath $exe | Out-Null

try {
  $rect = $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $rect = Get-AppRect
    if ($rect) { break }
  }
  if (-not $rect) { throw "FAIL: window not found" }
  Write-Output ("S1 initial rect: L={0} T={1} W={2} H={3}" -f $rect.L, $rect.T, ($rect.R - $rect.L), ($rect.B - $rect.T))
  Start-Sleep -Milliseconds 1000

  $vx = [Win]::GetSystemMetrics(76)
  $vw = [Win]::GetSystemMetrics(78)
  $JUNCTION = 2560   # right edge of primary monitor
  $SEC_RIGHT = 4000  # right edge of secondary monitor

  # ---- S2: move to secondary monitor ----
  DragWindow 3120 300
  Start-Sleep -Milliseconds 600
  $r2 = Get-AppRect
  Write-Output ("S2 on secondary: L={0} T={1}" -f $r2.L, $r2.T)
  Shot ($r2.L - 24) ($r2.T - 24) 368 518 (Join-Path $shots "mm_2_secondary.png")
  if ($r2.L -lt $JUNCTION) { throw ("FAIL S2: window did not reach secondary monitor, L={0}" -f $r2.L) }

  # ---- S3: junction must NOT collapse, must NOT jump ----
  $rPre = Get-AppRect
  $wW = $rPre.R - $rPre.L
  DragWindow ($JUNCTION - $wW) 300
  [Win]::SetCursorPos(1200, 800) | Out-Null
  Start-Sleep -Milliseconds 900
  $r3 = Get-AppRect
  $vis3 = [Math]::Min($r3.R, $vx + $vw) - [Math]::Max($r3.L, $vx)
  Write-Output ("S3 at junction: L={0} R={1} visible={2}" -f $r3.L, $r3.R, $vis3)
  Shot ($r3.L - 24) ($r3.T - 24) 420 518 (Join-Path $shots "mm_3_junction.png")
  if (($r3.L -lt ($JUNCTION - $wW - 40)) -or ($r3.L -gt ($JUNCTION - $wW + 40))) { throw ("FAIL S3: window jumped or collapsed at junction, L={0}" -f $r3.L) }
  if ($r3.R -gt ($JUNCTION + 40)) { throw ("FAIL S3: window jumped onto secondary, R={0}" -f $r3.R) }

  # ---- S4: collapse at secondary right edge (true outer edge) ----
  $targetL = $SEC_RIGHT - $wW
  DragWindow $targetL 300
  [Win]::SetCursorPos(3000, 800) | Out-Null
  Start-Sleep -Milliseconds 900
  $r4 = Get-AppRect
  $vis4 = [Math]::Min($r4.R, $vx + $vw) - [Math]::Max($r4.L, $vx)
  Write-Output ("S4 collapsed at secondary right: L={0} visible={1}" -f $r4.L, $vis4)
  Shot ($SEC_RIGHT - 300) ($r4.T - 40) 320 ($r4.B - $r4.T + 80) (Join-Path $shots "mm_4_collapsed_sec.png")
  if ($vis4 -gt 30) { throw ("FAIL S4: expected collapsed strip but visible={0}" -f $vis4) }

  # ---- S5: hover expand -> restore ORIGINAL position on secondary ----
  [Win]::SetCursorPos(($SEC_RIGHT - 4), ($r4.T + 150)) | Out-Null
  Start-Sleep -Milliseconds 900
  $r5 = Get-AppRect
  Write-Output ("S5 expanded: L={0} T={1} (expect ~{2}, ~300)" -f $r5.L, $r5.T, $targetL)
  Shot ($r5.L - 24) ($r5.T - 24) 400 560 (Join-Path $shots "mm_5_restored_sec.png")
  if ([Math]::Abs($r5.L - $targetL) -gt 12) { throw ("FAIL S5: not restored to original X, L={0}" -f $r5.L) }
  if ([Math]::Abs($r5.T - 300) -gt 12) { throw ("FAIL S5: not restored to original Y, T={0}" -f $r5.T) }
  if ($r5.L -lt $JUNCTION) { throw ("FAIL S5: restore jumped back to primary, L={0}" -f $r5.L) }

  # ---- S6: mouse away -> re-collapse ----
  [Win]::SetCursorPos(3000, 800) | Out-Null
  Start-Sleep -Milliseconds 1000
  $r6 = Get-AppRect
  $vis6 = [Math]::Min($r6.R, $vx + $vw) - [Math]::Max($r6.L, $vx)
  Write-Output ("S6 re-collapsed: L={0} visible={1}" -f $r6.L, $vis6)
  if ($vis6 -gt 30) { throw ("FAIL S6: expected re-collapse but visible={0}" -f $vis6) }

  # ---- S7: expand, drag to primary left edge -> collapse ----
  [Win]::SetCursorPos(($SEC_RIGHT - 4), ($r6.T + 150)) | Out-Null
  Start-Sleep -Milliseconds 900
  DragWindow 6 300
  [Win]::SetCursorPos(600, 800) | Out-Null
  Start-Sleep -Milliseconds 900
  $r7 = Get-AppRect
  $vis7 = [Math]::Min($r7.R, $vx + $vw) - [Math]::Max($r7.L, $vx)
  Write-Output ("S7 collapsed at primary left: L={0} visible={1}" -f $r7.L, $vis7)
  if ($vis7 -gt 30) { throw ("FAIL S7: expected collapsed but visible={0}" -f $vis7) }

  # ---- S8: hover expand -> restore on PRIMARY (no jump to secondary) ----
  [Win]::SetCursorPos(4, ($r7.T + 150)) | Out-Null
  Start-Sleep -Milliseconds 900
  $r8 = Get-AppRect
  Write-Output ("S8 expanded: L={0} T={1} (expect ~6, ~300)" -f $r8.L, $r8.T)
  Shot ($r8.L - 24) ($r8.T - 24) 368 518 (Join-Path $shots "mm_8_restored_primary.png")
  if ($r8.L -gt 16) { throw ("FAIL S8: not restored at primary left edge, L={0}" -f $r8.L) }
  if ([Math]::Abs($r8.T - 300) -gt 12) { throw ("FAIL S8: not restored to original Y, T={0}" -f $r8.T) }
  if ($r8.L -ge $JUNCTION) { throw ("FAIL S8: restore jumped to secondary, L={0}" -f $r8.L) }

  # ---- S9: bottom dead-zone clamp regression ----
  DragWindow 388 1421
  Start-Sleep -Milliseconds 600
  $r9 = Get-AppRect
  Write-Output ("S9 after bottom-dead-zone drag: T={0} B={1} (work bottom=1380)" -f $r9.T, $r9.B)
  Shot ($r9.L - 24) ($r9.T - 24) 368 518 (Join-Path $shots "mm_9_bottom_clamp.png")
  if ($r9.B -gt 1382) { throw ("FAIL S9: window bottom {0} exceeds work area 1380" -f $r9.B) }

  Write-Output "MULTIMON TEST PASSED"
} finally {
  Get-Process DesktopTodo -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Write-Output "app stopped"
}
