param(
    [Parameter(Mandatory=$true)]
    [string]$Message
)

$body = @{
    message = $Message
} | ConvertTo-Json -Compress

$response = Invoke-WebRequest `
    -Uri "https://ai-ayafumi-gourmet.onrender.com/test" `
    -Method POST `
    -ContentType "application/json; charset=utf-8" `
    -UseBasicParsing `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

$result = $response.Content | ConvertFrom-Json

Write-Host ""
Write-Host "=============================="
Write-Host "AI Ayafumi Gourmet"
Write-Host "=============================="
Write-Host ""
Write-Host "Input:"
Write-Host $result.message
Write-Host ""
Write-Host "Answer:"
Write-Host $result.answer
Write-Host ""