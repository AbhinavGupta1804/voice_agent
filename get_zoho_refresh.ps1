# Usage: .\get_zoho_refresh.ps1 "CODE" "CLIENT_ID" "CLIENT_SECRET"
# Generate a new code at Zoho Self Client first (codes expire in ~3 min).

param(
    [Parameter(Mandatory=$true)] [string]$Code,
    [Parameter(Mandatory=$true)] [string]$ClientId,
    [Parameter(Mandatory=$true)] [string]$ClientSecret
)

$body = @{
    grant_type    = "authorization_code"
    code          = $Code
    client_id     = $ClientId
    client_secret = $ClientSecret
}
try {
    $response = Invoke-WebRequest -Uri "https://accounts.zoho.in/oauth/v2/token" -Method Post -Body $body -UseBasicParsing
    $r = $response.Content | ConvertFrom-Json
    if ($r.refresh_token) {
        Write-Host "SUCCESS. Paste this into agency_backend\.env as ZOHO_REFRESH_TOKEN:"
        Write-Host $r.refresh_token
    } else {
        Write-Host "Response:" $response.Content
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
}
