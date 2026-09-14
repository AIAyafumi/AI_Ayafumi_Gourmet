$URL = "https://ai-ayafumi-gourmet.onrender.com/test"

$body = @{
    message = "堀之内でラーメン屋を探して"
} | ConvertTo-Json

Write-Host "========================================"
Write-Host "AI Ayafumi Gourmet Test"
Write-Host "========================================"
Write-Host ""
Write-Host "Sending request to Render..."
Write-Host ""

try {
    $response = Invoke-WebRequest `
        -Uri $URL `
        -Method POST `
        -ContentType "application/json" `
        -Body $body

    Write-Host "HTTP Status:" $response.StatusCode
    Write-Host ""
    Write-Host $response.Content
}
catch {
    Write-Host "========================================"
    Write-Host "ERROR"
    Write-Host "========================================"
    Write-Host ""
    Write-Host "Message:"
    Write-Host $_.Exception.Message
    Write-Host ""

    if ($_.Exception.Response) {
        Write-Host "HTTP Status:"
        Write-Host $_.Exception.Response.StatusCode

        Write-Host ""
        Write-Host "Response Body:"
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $errorBody = $reader.ReadToEnd()
            $reader.Close()
            Write-Host $errorBody
        }
        catch {
            Write-Host "Could not read response body."
        }
    }
}