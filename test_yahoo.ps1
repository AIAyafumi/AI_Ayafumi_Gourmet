param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$Message
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host ""
Write-Host "========================================"
Write-Host "Yahoo!ローカルサーチ テスト"
Write-Host "========================================"
Write-Host "検索文字列：" $Message
Write-Host ""

$body = @{
    message = $Message
} | ConvertTo-Json -Compress

$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)

try {

    $response = Invoke-WebRequest `
        -Uri "http://127.0.0.1:5000/test_yahoo" `
        -Method POST `
        -ContentType "application/json; charset=utf-8" `
        -Body $utf8Body `
        -UseBasicParsing

    Write-Host ""
    Write-Host "========================================"
    Write-Host "Yahoo! API レスポンス"
    Write-Host "========================================"
    Write-Host ""

    $response.Content |
        ConvertFrom-Json |
        ConvertTo-Json -Depth 10

}
catch {

    Write-Host ""
    Write-Host "========================================"
    Write-Host "エラー"
    Write-Host "========================================"
    Write-Host ""

    Write-Host $_.Exception.Message
}
