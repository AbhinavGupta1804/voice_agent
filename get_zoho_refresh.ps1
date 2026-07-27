# Exchange Zoho Self Client auth code for refresh token.
# Reads CLIENT_ID / CLIENT_SECRET from agency_backend\.env
# Code: first argument OR ZOHO_AUTH_CODE in .env (expires ~10 min)

param(
    [Parameter(Mandatory = $false)] [string]$Code
)

$envFile = Join-Path $PSScriptRoot "agency_backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env not found at $envFile"
    exit 1
}

function Get-EnvValue($key) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$key=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

$ClientId = Get-EnvValue "ZOHO_CLIENT_ID"
$ClientSecret = Get-EnvValue "ZOHO_CLIENT_SECRET"
$AccountsDomain = Get-EnvValue "ZOHO_ACCOUNTS_DOMAIN"
if (-not $AccountsDomain) { $AccountsDomain = "https://accounts.zoho.in" }

if (-not $Code) { $Code = Get-EnvValue "ZOHO_AUTH_CODE" }

if (-not $ClientId -or -not $ClientSecret) {
    Write-Host "ERROR: Set ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET in agency_backend\.env"
    exit 1
}
if (-not $Code) {
    Write-Host "ERROR: No auth code."
    Write-Host "  1. Zoho API Console -> Generate Code (comma-separated scopes)"
    Write-Host "  2. Add to .env: ZOHO_AUTH_CODE=your_code_here"
    Write-Host "  3. Run: .\get_zoho_refresh.ps1"
    Write-Host "  Or: .\get_zoho_refresh.ps1 `"your_code_here`""
    exit 1
}

$tokenUrl = "$($AccountsDomain.TrimEnd('/'))/oauth/v2/token"
$body = @{
    grant_type    = "authorization_code"
    code          = $Code
    client_id     = $ClientId
    client_secret = $ClientSecret
}

try {
    $response = Invoke-WebRequest -Uri $tokenUrl -Method Post -Body $body -UseBasicParsing
    $r = $response.Content | ConvertFrom-Json
    if ($r.refresh_token) {
        Write-Host "SUCCESS. refresh_token received."
        Write-Host $r.refresh_token
        # Update .env ZOHO_REFRESH_TOKEN
        $lines = Get-Content $envFile
        $updated = $false
        $newLines = foreach ($line in $lines) {
            if ($line -match "^\s*ZOHO_REFRESH_TOKEN=") {
                $updated = $true
                "ZOHO_REFRESH_TOKEN=$($r.refresh_token)"
            }
            elseif ($line -match "^\s*ZOHO_AUTH_CODE=") {
                continue  # remove one-time code
            }
            else { $line }
        }
        if (-not $updated) { $newLines += "ZOHO_REFRESH_TOKEN=$($r.refresh_token)" }
        $newLines | Set-Content $envFile -Encoding UTF8
        Write-Host "Updated agency_backend\.env -> ZOHO_REFRESH_TOKEN (removed ZOHO_AUTH_CODE if present)"
    }
    else {
        Write-Host "Response:" $response.Content
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
}
