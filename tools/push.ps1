# 바뀐 것을 모두 커밋하고 올린다. push.bat 이 부른다.
#
# ⚠️ 이 파일은 UTF-8(BOM) 으로 둔다. 윈도 PowerShell 5.1 은 BOM 이 없으면
#    ANSI(CP949)로 읽어 한글이 깨진다.
#
#   메시지 창에서 그냥 Enter → 메시지 없이 올린다.
#   내용을 치고 Enter        → 그 내용 그대로 올린다.
#   취소(Esc)               → 아무것도 하지 않는다.

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:LC_ALL = 'C.UTF-8'

function Say($m)  { Write-Host "[*] $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

git add -A
if ($LASTEXITCODE) { Fail 'git add 실패' }

# 비밀 파일이 섞였으면 멈춘다. .gitignore 가 막고 있지만 한 번 더 본다.
$staged = @(git -c core.quotepath=false diff --cached --name-only)
$secret = $staged | Where-Object { $_ -match '(^|/)(api_keys\.txt|\.env)$' }
if ($secret) {
    git reset -q
    Fail ("비밀 파일이 커밋에 들어가려 합니다: " + ($secret -join ', ') + " — 중단했습니다")
}

if ($staged.Count -gt 0) {
    Add-Type -AssemblyName System.Windows.Forms
    $list = ($staged | Select-Object -First 12) -join "`r`n"
    if ($staged.Count -gt 12) { $list += "`r`n... 외 $($staged.Count - 12)개" }

    $f = New-Object Windows.Forms.Form
    $f.Text = '커밋 메시지'
    $f.Size = New-Object Drawing.Size(520, 400)
    $f.StartPosition = 'CenterScreen'
    $f.TopMost = $true
    $f.FormBorderStyle = 'FixedDialog'
    $f.MaximizeBox = $false
    $f.Font = New-Object Drawing.Font('맑은 고딕', 9)

    $lbl = New-Object Windows.Forms.Label
    $lbl.Text = "바뀐 파일 $($staged.Count)개:"
    $lbl.SetBounds(12, 10, 480, 20)

    $files = New-Object Windows.Forms.TextBox
    $files.Multiline = $true; $files.ReadOnly = $true; $files.ScrollBars = 'Vertical'
    $files.Text = $list
    $files.SetBounds(12, 32, 480, 200)
    $files.TabStop = $false

    $lbl2 = New-Object Windows.Forms.Label
    $lbl2.Text = '메시지 (비워 두고 Enter 면 메시지 없이 올립니다):'
    $lbl2.SetBounds(12, 244, 480, 20)

    $box = New-Object Windows.Forms.TextBox
    $box.SetBounds(12, 266, 480, 24)

    $ok = New-Object Windows.Forms.Button
    $ok.Text = '올리기'; $ok.DialogResult = 'OK'
    $ok.SetBounds(316, 310, 85, 30)
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = '취소'; $cancel.DialogResult = 'Cancel'
    $cancel.SetBounds(407, 310, 85, 30)

    $f.Controls.AddRange(@($lbl, $files, $lbl2, $box, $ok, $cancel))
    $f.AcceptButton = $ok
    $f.CancelButton = $cancel
    $f.Add_Shown({ $box.Focus() })

    if ($f.ShowDialog() -ne 'OK') {
        git reset -q
        Say '취소했습니다. 아무것도 올리지 않았습니다.'
        exit 0
    }

    $msg = $box.Text.Trim()

    # 메시지는 파일로 넘긴다 — 명령줄로 넘기면 코드페이지 때문에 한글이 깨질 수 있다.
    $tmp = [IO.Path]::GetTempFileName()
    [IO.File]::WriteAllText($tmp, $msg, (New-Object Text.UTF8Encoding($false)))
    git commit -q --allow-empty-message -F $tmp
    $code = $LASTEXITCODE
    Remove-Item $tmp
    if ($code) { Fail '커밋 실패' }
    if ($msg) { Say "커밋했습니다: $msg" } else { Say '커밋했습니다 (메시지 없음)' }
} else {
    Say '새로 바뀐 파일은 없습니다. 아직 안 올린 커밋이 있으면 올립니다.'
}

Say '올리는 중...'
git push -u origin HEAD
if ($LASTEXITCODE) { Fail 'push 실패 — 위 메시지를 확인하세요 (먼저 다른 PC 에서 올린 게 있으면 run.bat 으로 받은 뒤 다시).' }
Say '완료했습니다.'
