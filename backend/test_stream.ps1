$body = @{
    question = "What are Chris' favorite business ideas?"
    client_id = "koerner-office"
    mode = "audience"
    history = @()
} | ConvertTo-Json -Compress

$body | Out-File -FilePath body.json -Encoding utf8 -NoNewline

curl.exe -N -X POST http://localhost:8000/api/query/stream `
    -H "Content-Type: application/json" `
    --data-binary "@body.json"
