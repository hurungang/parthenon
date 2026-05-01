<#
.SYNOPSIS
    Inventory and optionally sync change-*.prompt.md files across all IDE prompt directories.

.DESCRIPTION
    Scans four IDE prompt folders for change-*.prompt.md files, compares timestamps and content,
    and reports which files are MISSING, DIVERGED (content conflict), or IN-SYNC.
    When -Apply is specified, copies newer/missing files to all target folders automatically.
    DIVERGED files are never auto-resolved; they require AI-assisted merge.

.PARAMETER Apply
    When set, automatically copies MISSING files (newest version) to all folders that lack them.
    DIVERGED files are always reported but never touched automatically.

.PARAMETER FileName
    Optional. Filter to a specific prompt filename (e.g. "change-apply.prompt.md").

.EXAMPLE
    # Dry-run inventory report
    ./sync-sdd-prompts.ps1

    # Auto-copy MISSING files, report DIVERGED for manual merge
    ./sync-sdd-prompts.ps1 -Apply

    # Check a single file
    ./sync-sdd-prompts.ps1 -FileName change-refinement.prompt.md
#>
param(
    [switch]$Apply,
    [string]$FileName = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Folder definitions ──────────────────────────────────────────────────────
$Folders = [ordered]@{
    ".copilot"        = "$env:USERPROFILE\.copilot\prompts"
    "code-insiders"   = "$env:USERPROFILE\AppData\Roaming\Code - Insiders\User\prompts"
    "code"            = "$env:USERPROFILE\AppData\Roaming\Code\User\prompts"
    "agents-insiders" = "$env:USERPROFILE\AppData\Roaming\Agents - Insiders\User\prompts"
}

# Verify folders exist (warn, not error, if one is missing — IDE may not be installed)
foreach ($alias in $Folders.Keys) {
    if (-not (Test-Path $Folders[$alias])) {
        Write-Warning "Folder not found (skipped): [$alias] $($Folders[$alias])"
    }
}

$existingFolders = $Folders.GetEnumerator() | Where-Object { Test-Path $_.Value }

# ── Collect all change-* files ───────────────────────────────────────────────
$pattern = if ($FileName) { $FileName } else { "change-*.prompt.md" }

$allFiles = @{}  # key = filename, value = list of {Alias, Path, LastWrite, Content}

foreach ($entry in $existingFolders) {
    $alias = $entry.Key
    $folder = $entry.Value
    Get-ChildItem -Path $folder -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
        $fname = $_.Name
        if (-not $allFiles.ContainsKey($fname)) { $allFiles[$fname] = [System.Collections.Generic.List[object]]::new() }
        $allFiles[$fname].Add([PSCustomObject]@{
            Alias     = $alias
            Path      = $_.FullName
            LastWrite = $_.LastWriteTime
            Content   = Get-Content -Path $_.FullName -Raw -Encoding UTF8
        })
    }
}

if ($allFiles.Count -eq 0) {
    Write-Host "No change-*.prompt.md files found in any prompt folder." -ForegroundColor Yellow
    exit 0
}

$totalFolders = ($existingFolders | Measure-Object).Count
$results = [System.Collections.Generic.List[object]]::new()

# ── Analyse each file ────────────────────────────────────────────────────────
foreach ($fname in ($allFiles.Keys | Sort-Object)) {
    $copies = $allFiles[$fname]
    $presentIn = @($copies | Select-Object -ExpandProperty Alias)

    # Folders missing this file
    $missingIn = @($existingFolders | Where-Object { $_.Key -notin $presentIn } | Select-Object -ExpandProperty Key)

    # Newest copy (by timestamp)
    $newestCopy = $copies | Sort-Object LastWrite -Descending | Select-Object -First 1

    # Determine if content diverges among the newest copies
    # "newest copies" = all copies whose timestamp is within 2 seconds of the newest
    $newestTime = $newestCopy.LastWrite
    $newestGroup = @($copies | Where-Object { ($newestTime - $_.LastWrite).TotalSeconds -lt 2 })
    $uniqueContents = @($newestGroup | Select-Object -ExpandProperty Content | Sort-Object -Unique)

    # Folders that have the file but with stale (older) content vs the newest copy
    $staleIn = @($copies | Where-Object { $_.Content -ne $newestCopy.Content } | Select-Object -ExpandProperty Alias)
    # Combined: folders that need the newest version (physically missing OR stale content)
    $needsUpdateIn = @(($missingIn + $staleIn) | Sort-Object -Unique)

    $status = if ($needsUpdateIn.Count -gt 0 -and $uniqueContents.Count -gt 1) {
        "MISSING+DIVERGED"
    } elseif ($needsUpdateIn.Count -gt 0) {
        "MISSING"
    } elseif ($uniqueContents.Count -gt 1) {
        "DIVERGED"
    } else {
        "IN-SYNC"
    }

    $results.Add([PSCustomObject]@{
        File          = $fname
        Status        = $status
        MissingIn     = $missingIn -join ", "
        StaleIn       = $staleIn -join ", "
        NeedsUpdateIn = $needsUpdateIn -join ", "
        PresentIn     = $presentIn -join ", "
        NewestAt      = $newestCopy.LastWrite.ToString("yyyy-MM-dd HH:mm:ss")
        NewestFrom    = $newestCopy.Alias
        NewestPath    = $newestCopy.Path
        AllCopies     = $copies
    })
}

# ── Print report ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  SDD Prompts Sync — Inventory Report" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$statusColors = @{
    "IN-SYNC"         = "Green"
    "MISSING"         = "Yellow"
    "DIVERGED"        = "Red"
    "MISSING+DIVERGED"= "Red"
}

foreach ($r in $results) {
    $color = $statusColors[$r.Status]
    Write-Host "  [$($r.Status)]".PadRight(22) -ForegroundColor $color -NoNewline
    Write-Host $r.File -ForegroundColor White
    if ($r.Status -ne "IN-SYNC") {
        if ($r.MissingIn) {
            Write-Host "    Missing in : $($r.MissingIn)" -ForegroundColor DarkYellow
        }
        if ($r.StaleIn) {
            Write-Host "    Stale in   : $($r.StaleIn) (file exists but content is outdated)" -ForegroundColor DarkYellow
        }
        Write-Host "    Newest     : $($r.NewestAt) in [$($r.NewestFrom)]" -ForegroundColor DarkGray
        Write-Host "    Source     : $($r.NewestPath)" -ForegroundColor DarkGray
        if ($r.Status -like "*DIVERGED*") {
            Write-Host "    ⚠ Content differs between newer copies — AI merge required" -ForegroundColor Red
            # Print per-copy details for the agent to act on
            foreach ($c in $r.AllCopies | Sort-Object LastWrite -Descending) {
                Write-Host "      [$($c.Alias)] $($c.LastWrite.ToString('yyyy-MM-dd HH:mm:ss'))  $($c.Path)" -ForegroundColor DarkGray
            }
        }
    }
    Write-Host ""
}

# ── Summary ───────────────────────────────────────────────────────────────────
$inSync        = @($results | Where-Object Status -eq "IN-SYNC").Count
$missing       = @($results | Where-Object { $_.Status -in @("MISSING","MISSING+DIVERGED") }).Count
$diverged      = @($results | Where-Object { $_.Status -in @("DIVERGED","MISSING+DIVERGED") }).Count

Write-Host "  Summary: $($results.Count) files | " -NoNewline
Write-Host "$inSync in-sync" -ForegroundColor Green -NoNewline
Write-Host " | " -NoNewline
Write-Host "$missing missing" -ForegroundColor Yellow -NoNewline
Write-Host " | " -NoNewline
Write-Host "$diverged diverged" -ForegroundColor Red
Write-Host ""

# ── Helper: archive a file before overwriting it ─────────────────────────────
# Archives into <promptsFolder>/_archive/<runTimestamp>/<filename>
$RunTimestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"

function Invoke-Archive {
    param(
        [string]$FilePath,   # full path to the file being replaced
        [string]$FolderAlias # IDE alias (for logging)
    )
    if (-not (Test-Path $FilePath)) { return }  # nothing to archive
    $archiveDir = Join-Path (Split-Path $FilePath) "_archive\$RunTimestamp"
    if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null }
    $archiveDest = Join-Path $archiveDir (Split-Path $FilePath -Leaf)
    Copy-Item -Path $FilePath -Destination $archiveDest -Force
    Write-Host "    Archived  [$FolderAlias] -> _archive\$RunTimestamp\$(Split-Path $FilePath -Leaf)" -ForegroundColor DarkGray
}

# ── Auto-copy MISSING files (only when -Apply and status is MISSING, not DIVERGED) ──
if ($Apply) {
    $toCopy = $results | Where-Object { $_.Status -eq "MISSING" }
    if ($toCopy.Count -eq 0) {
        Write-Host "  Nothing to copy automatically." -ForegroundColor DarkGray
    } else {
        Write-Host "  Applying copies (-Apply)..." -ForegroundColor Cyan
        foreach ($r in $toCopy) {
            foreach ($alias in $r.NeedsUpdateIn -split ", ") {
                $destFolder = $Folders[$alias]
                if (Test-Path $destFolder) {
                    $dest = Join-Path $destFolder $r.File
                    # Archive existing file if present (older version being replaced)
                    Invoke-Archive -FilePath $dest -FolderAlias $alias
                    Copy-Item -Path $r.NewestPath -Destination $dest -Force
                    Write-Host "    Copied    [$($r.NewestFrom)] -> [$alias]  $($r.File)" -ForegroundColor Green
                }
            }
        }
    }

    $divergedFiles = @($results | Where-Object { $_.Status -like "*DIVERGED*" })
    if ($divergedFiles.Count -gt 0) {
        Write-Host ""
        Write-Host "  The following files have conflicting edits and require AI merge:" -ForegroundColor Red
        foreach ($r in $divergedFiles) {
            Write-Host "    - $($r.File)" -ForegroundColor Yellow
        }
        Write-Host "  Re-run without -Apply and use the sdd-prompts-sync skill to resolve." -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  Done. Re-run without -Apply to verify." -ForegroundColor Cyan
}

# ── When writing a merged result from AI merge, call this helper ──────────────
# Usage (from agent, after AI merge produces $mergedContent):
#
#   foreach ($alias in $Folders.Keys) {
#       $dest = Join-Path $Folders[$alias] "change-foo.prompt.md"
#       Invoke-Archive -FilePath $dest -FolderAlias $alias
#       Set-Content -Path $dest -Value $mergedContent -Encoding UTF8
#   }
#
# The archive step runs automatically so the pre-merge versions are preserved.
