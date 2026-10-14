# Final comprehensive smoke test (ASCII only)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

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
  $w = $rect.R - $rect.L; $h = $rect.B - $rect.T
  Write-Output ("S1 initial rect: L={0} T={1} W={2} H={3}" -f $rect.L, $rect.T, $w, $h)
  Start-Sleep -Milliseconds 1200
  $m = 24
  Shot ($rect.L - $m) ($rect.T - $m) ($w + 2*$m) ($h + 2*$m) (Join-Path $shots "final_1_initial.png")

  # primary work area bottom (taskbar excluded)
  $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
  Write-Output ("primary work area: {0},{1} {2}x{3}" -f $wa.X, $wa.Y, $wa.Width, $wa.Height)

  # S2 drag to bottom edge -> must stay inside work area
  DragTo ($rect.L + [int]($w * 0.35)) ($rect.T + 18) ($rect.L + 100) ($wa.Y + $wa.Height + 300)
  Start-Sleep -Milliseconds 600
  $r2 = Get-AppRect
  Write-Output ("S2 after bottom-drag: T={0} B={1} (work bottom={2})" -f $r2.T, $r2.B, ($wa.Y + $wa.Height))
  if (($r2.B - ($wa.Y + $wa.Height)) -gt 2) { throw ("FAIL: window bottom {0} exceeds work area {1}" -f $r2.B, ($wa.Y + $wa.Height)) }

  # S3 drag to left edge -> collapse to strip
  $vx = [Win]::GetSystemMetrics(76)
  DragTo ($r2.L + [int]($w * 0.35)) ($r2.T + 18) ($vx + 6) ($r2.T + 100)
  [Win]::SetCursorPos(($vx + 500), ($r2.T + 300)) | Out-Null
  Start-Sleep -Milliseconds 900
  $r3 = Get-AppRect
  $vis3 = [Math]::Min($r3.R, $vx + $vw) - [Math]::Max($r3.L, $vx)
  $vw = [Win]::GetSystemMetrics(78)
  $vis3 = [Math]::Min($r3.R, $vx + $vw) - [Math]::Max($r3.L, $vx)
  Write-Output ("S3 after left-drop: L={0} visible={1}" -f $r3.L, $vis3)
  Shot $vx ($r3.T - 40) 300 ($r3.B - $r3.T + 80) (Join-Path $shots "final_2_collapsed.png")
  if ($vis3 -gt 30) { throw "FAIL: expected collapsed strip but visible=$vis3" }

  # S4 hover strip -> expand, verify content fully painted
  [Win]::SetCursorPos(($vx + 3), ($r3.T + 150)) | Out-Null
  Start-Sleep -Milliseconds 800
  $r4 = Get-AppRect
  Write-Output ("S4 after hover: L={0} T={1} B={2}" -f $r4.L, $r4.T, $r4.B)
  Shot ($r4.L - $m) ($r4.T - $m) (($r4.R - $r4.L) + 2*$m) (($r4.B - $r4.T) + 2*$m) (Join-Path $shots "final_3_expanded.png")

  # S5 mouse away -> re-collapse
  [Win]::SetCursorPos(($vx + 700), ($r4.T + 100)) | Out-Null
  Start-Sleep -Milliseconds 1000
  $r5 = Get-AppRect
  $vis5 = [Math]::Min($r5.R, $vx + $vw) - [Math]::Max($r5.L, $vx)
  Write-Output ("S5 after mouse-away: L={0} visible={1}" -f $r5.L, $vis5)
  if ($vis5 -gt 30) { throw "FAIL: expected re-collapse but visible=$vis5" }

  Write-Output "FINAL TEST PASSED"
} finally {
  Get-Process DesktopTodo -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Write-Output "app stopped"
}
