<#
.SYNOPSIS
    云端 → 本地 单向下行同步（apply-copilot 网申助手）。

.DESCRIPTION
    把云端 copilot 的投递台账（/opt/copilot/skill/state/applications.json）以「以云端为准」
    的方式同步到本地 autumn-recruitment-tracker 的 state/applications.json。

    执行流程：
      1. scp 云端文件到本地临时文件。
      2. 严格校验云端文件：JSON 可解析、schema 合法（顶层为数组或含 applications/records
         结构）、记录数 > 0。任一不满足 → 立即退出，且绝不触碰本地文件。
      3. 备份本地文件 → applications.json.bak_sync_<YYYYMMDD-HHMMSS>（同目录）。
      4. 原子覆盖本地文件为云端版本（先写同目录临时文件再改名，绝不留下半截文件）。
      5. 差异报告：同步前后条数，并逐条列出「本地有而云端没有」的记录
         （按 company+title+date 三元组比对，company 用规范化 + 别名分组比较）——
         这就是同步后会被丢弃的内容。

.PARAMETER Local
    本地台账路径。默认 D:\WorkBuddyData\.workbuddy\skills\autumn-recruitment-tracker\state\applications.json

.PARAMETER Remote
    scp 远端源。默认 root@124.223.15.11:/opt/copilot/skill/state/applications.json

.PARAMETER DryRun
    干跑：只做 1、2、5 步（拉取、校验、差异报告），不写本地文件、不做备份。

.PARAMETER CloudFile
    可选：指定一个本地文件当作「云端源」，跳过 scp。仅用于离线自测/回归（默认空 = 走 scp）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\sync_from_cloud.ps1 -DryRun
    干跑，只打印差异报告。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\sync_from_cloud.ps1
    真实同步（备份 + 覆盖）。

.NOTES
    全程只写本地 state 目录（备份 + 覆盖），不改动云端任何文件。
    退出码：0 成功；非 0 失败。
#>
[CmdletBinding()]
param(
    [string]$Local  = 'D:\WorkBuddyData\.workbuddy\skills\autumn-recruitment-tracker\state\applications.json',
    [string]$Remote = 'root@124.223.15.11:/opt/copilot/skill/state/applications.json',
    [string]$CloudFile = '',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# 注意：不预置 $LASTEXITCODE。若在调用后直接读它，StrictMode 会因「未初始化变量」抛错，
# 而 spawn 失败（子进程根本没执行）时它也不存在——这两种情况都必须显式判型（见步骤 1）。

# 归一化为绝对路径：步骤 4 使用 .NET File API（File.Replace/Move），它按「进程 CWD」
# 解析相对路径，与 PowerShell 的当前位置可能不同，故提前转绝对，避免语义分叉。
if (-not [System.IO.Path]::IsPathRooted($Local)) {
    $Local = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Local))
}

# ------------------------------------------------------------------ 公司名规范化
# 与 apply-copilot/company_util.py 保持一致：NFKC + 去首尾空格；同主体别名分组。
function Get-NormCompany {
    param([string]$Name)
    if ($null -eq $Name) { return '' }
    $t = ([string]$Name).Trim()
    try {
        $t = $t.Normalize([System.Text.NormalizationForm]::FormKC)
    } catch {
        # 某些代理对字符不支持的极端情况下退化：仅做 trim
    }
    return $t.Trim()
}

# 同主体别名白名单（镜像 company_util.COMPANY_ALIAS）。只有登记在此的才算同一家公司。
$CompanyAlias = [ordered]@{
    '字节跳动' = @('字节', '字节跳动', '字节跳动 ByteDance', 'ByteDance', 'ByeDance')
    '腾讯科技' = @('腾讯', '腾讯科技', 'Tencent', '深圳市腾讯计算机系统有限公司')
    '阿里巴巴' = @('阿里', '阿里巴巴', '阿里巴巴集团', 'Alibaba')
    '百度'     = @('百度', '百度在线', 'Baidu')
    '美团'     = @('美团', '美团点评', 'Meituan')
    '京东'     = @('京东', '京东集团', 'JD')
    '网易'     = @('网易', 'NetEase')
    '小米'     = @('小米', '小米科技', 'Xiaomi')
    '华为'     = @('华为', '华为技术', 'Huawei')
    '商汤科技' = @('商汤', '商汤科技', 'SenseTime')
    '银河通用' = @('银河通用', '银河通用 Galbot', 'Galbot')
    '天演资本' = @('天演', '天演资本')
    '宽德投资' = @('宽德', '宽德投资')
    '明汯投资' = @('明汯', '明汯投资')
}

# 反向索引：规范化公司名 → 所属别名分组名
$AliasGroupOf = @{}
foreach ($group in $CompanyAlias.Keys) {
    foreach ($member in $CompanyAlias[$group]) {
        $AliasGroupOf[(Get-NormCompany $member)] = $group
    }
}

function Get-CanonCompany {
    param([string]$Name)
    $n = Get-NormCompany $Name
    if ($AliasGroupOf.ContainsKey($n)) { return [string]$AliasGroupOf[$n] }
    return $n
}

# 安全取字段（StrictMode 下访问不存在的属性会抛错，故统一走这里；
# 不用 .PSObject.Properties.Name 这种成员枚举写法——对空对象 {} 会抛“找不到属性 Name”）
function Get-Field {
    param($Obj, [string]$Name)
    if ($null -eq $Obj) { return $null }
    if ($Obj -is [System.Collections.IDictionary]) {
        if ($Obj.Contains($Name)) { return $Obj[$Name] }
        return $null
    }
    foreach ($p in $Obj.PSObject.Properties) {
        if ($p.Name -eq $Name) { return $p.Value }
    }
    return $null
}

# 顶层键名列表（同样规避成员枚举对空对象的坑）
function Get-ObjectKeys {
    param($Obj)
    if ($Obj -is [System.Collections.IDictionary]) { return @($Obj.Keys) }
    $out = New-Object System.Collections.ArrayList
    foreach ($p in $Obj.PSObject.Properties) { [void]$out.Add($p.Name) }
    return @($out)
}

# 解析可执行文件：优先 PATH，其次常见安装位置（应对受限 shell 里 Get-Command 找不到的情况）
function Resolve-Executable {
    param([string]$Name, [string[]]$ExtraPaths)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($p in $ExtraPaths) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function Get-TripleDate {
    param($Rec)
    $d = Get-Field $Rec 'applied_at'
    if ([string]::IsNullOrWhiteSpace([string]$d)) {
        $sh = Get-Field $Rec 'stage_history'
        if ($sh -is [System.Array] -and $sh.Count -gt 0) { $d = Get-Field $sh[-1] 'date' }
    }
    if ($null -eq $d) { return '' }
    return ([string]$d).Trim()
}

function Get-TripleKey {
    param($Rec)
    $co = Get-CanonCompany ([string](Get-Field $Rec 'company'))
    $ti = ([string](Get-Field $Rec 'title')).Trim()
    $dt = Get-TripleDate $Rec
    # 用不可见分隔符拼键，避免公司名/标题含空格或连字符造成的歧义
    $sep = [char]31
    return ($co + $sep + $ti + $sep + $dt)
}

# ------------------------------------------------------------------ schema 解析
# 显式 schema 口径（与文档一致，接受的形态）：
#   ① 顶层数组                       —— 元素即记录
#   ② {"applications": <容器>}      —— 容器可为「对象字典 {id: 记录}」或「数组」
#   ③ {"records": <容器>}           —— 同上
#   ④ {"items": <容器>}             —— 同上（兼容旧口径，见 QA P2-4 备注）
# 记录必须是对象。返回 @{ Ok = $bool; Reason = ''; Records = @() }
function Read-RecordSet {
    param($Obj)

    if ($null -eq $Obj) { return @{ Ok = $false; Reason = '解析结果为空'; Records = @() } }

    $records = New-Object System.Collections.ArrayList

    if ($Obj -is [System.Array]) {
        foreach ($r in $Obj) { [void]$records.Add($r) }
    } elseif ($Obj -is [System.Collections.IDictionary] -or $Obj -is [System.Management.Automation.PSCustomObject]) {
        # 显式判型 + 取键，避免对空对象 {} 走成员枚举（.PSObject.Properties.Name）抛内部异常
        $names = @(Get-ObjectKeys $Obj)
        $containerKey = $null
        foreach ($k in @('applications', 'records', 'items')) {
            if ($names -contains $k) { $containerKey = $k; break }
        }
        if ($null -eq $containerKey) {
            if ($names.Count -eq 0) {
                return @{ Ok = $false; Reason = '云端文件 schema 不符合预期：是一个空对象 {}，缺少 applications/records 键'; Records = @() }
            }
            return @{ Ok = $false; Reason = ("云端文件 schema 不符合预期：缺少 applications/records 键（现有键：{0}）" -f ($names -join ', ')); Records = @() }
        }
        $container = $Obj.$containerKey
        if ($container -is [System.Array]) {
            foreach ($r in $container) { [void]$records.Add($r) }
        } elseif ($null -ne $container) {
            if ($container -is [System.Collections.IDictionary]) {
                foreach ($v in $container.Values) { [void]$records.Add($v) }
            } else {
                foreach ($p in $container.PSObject.Properties) { [void]$records.Add($p.Value) }
            }
        }
    } else {
        return @{ Ok = $false; Reason = ("顶层类型不符合预期：{0}（应为数组或对象容器）" -f $Obj.GetType().FullName); Records = @() }
    }

    # 记录必须是对象（含 company/title 之类的字段），否则视为 schema 不符
    foreach ($r in $records) {
        if ($null -eq $r -or $r -is [string] -or $r -is [System.ValueType]) {
            return @{ Ok = $false; Reason = '记录集里出现了非对象元素'; Records = @() }
        }
    }

    return @{ Ok = $true; Reason = ''; Records = @($records) }
}

# ------------------------------------------------------------------ 主流程
$startedAt = Get-Date
Write-Output ('=' * 68)
Write-Output ("云端 -> 本地 单向下行同步    " + $startedAt.ToString('yyyy-MM-dd HH:mm:ss'))
if ($DryRun) { Write-Output '模式：DRY-RUN（只报告，不写本地）' } else { Write-Output '模式：真实同步（备份 + 覆盖）' }
Write-Output ("本地: {0}" -f $Local)
Write-Output ("云端: {0}" -f $Remote)
Write-Output ('=' * 68)

$tmpCloud = Join-Path $env:TEMP ('cloud_applications_' + [guid]::NewGuid().ToString('N') + '.json')
$tmpWrite = $null
$rollbackSource = $null

try {
    # ---- 步骤 1：拉取云端到临时文件 ----
    Write-Output ''
    Write-Output '[1/5] 拉取云端台账 ...'
    if ($CloudFile) {
        if (-not (Test-Path -LiteralPath $CloudFile)) {
            throw ("指定的 -CloudFile 不存在：{0}" -f $CloudFile)
        }
        Copy-Item -LiteralPath $CloudFile -Destination $tmpCloud -Force
        Write-Output ("      使用本地源文件（-CloudFile）: {0}" -f $CloudFile)
    } else {
        $scpExe = Resolve-Executable -Name 'scp' -ExtraPaths @(
            (Join-Path $env:SystemRoot 'System32\OpenSSH\scp.exe'),
            'C:\Program Files\Git\usr\bin\scp.exe',
            'C:\Program Files\OpenSSH\scp.exe'
        )
        if (-not $scpExe) {
            throw '找不到 scp：请安装 Windows OpenSSH 客户端（设置 > 应用 > 可选功能）或 Git，并确保 scp 在 PATH 中。'
        }
        Write-Output ("      使用 scp: {0}" -f $scpExe)
        # 用 Process 显式启动，绕开 $LASTEXITCODE 的两个坑：
        #   ① spawn 被拦截/失败时该变量根本不存在（StrictMode 读取即抛错）；
        #   ② 会话里残留的上一次退出码会被误当成 scp 的退出码（掩盖 spawn 失败）。
        # Process.ExitCode 只有在进程真的启动并退出后才有值，语义无歧义。
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $scpExe
        $psi.Arguments = '-o StrictHostKeyChecking=no -q -B "' + $Remote + '" "' + $tmpCloud + '"'
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $proc = $null
        try {
            $proc = [System.Diagnostics.Process]::Start($psi)
        } catch {
            throw ("无法启动 scp（{0}）：{1}" -f $scpExe, $_.Exception.Message)
        }
        $scpStdout = $proc.StandardOutput.ReadToEnd()
        $scpStderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit()
        if ($proc.ExitCode -ne 0) {
            throw ("scp 拉取失败（exit={0}）：{1}" -f $proc.ExitCode, ($scpStderr + $scpStdout).Trim())
        }
        if (-not (Test-Path -LiteralPath $tmpCloud)) { throw 'scp 进程退出码为 0，但未找到临时文件' }
    }
    $tmpSize = (Get-Item -LiteralPath $tmpCloud).Length
    Write-Output ("      已拉取 {0} 字节" -f $tmpSize)

    # ---- 步骤 2：严格校验云端文件 ----
    Write-Output '[2/5] 校验云端 JSON 与 schema ...'
    $cloudText = Get-Content -LiteralPath $tmpCloud -Raw -Encoding UTF8
    $cloudObj = $null
    try {
        $cloudObj = $cloudText | ConvertFrom-Json
    } catch {
        throw ("云端 JSON 解析失败：{0}" -f $_.Exception.Message)
    }
    $cloudRead = Read-RecordSet $cloudObj
    if (-not $cloudRead.Ok) { throw ("云端 schema 校验失败：{0}" -f $cloudRead.Reason) }
    $cloudRecords = @($cloudRead.Records)
    if ($cloudRecords.Count -le 0) { throw ("云端 schema 校验失败：记录数 = {0}" -f $cloudRecords.Count) }
    Write-Output ("      校验通过：云端记录数 = {0}" -f $cloudRecords.Count)

    # ---- 读取本地（仅用于差异报告；本地损坏不阻断「以云端为准」的同步）----
    $localExists = Test-Path -LiteralPath $Local
    $localRecords = @()
    $localParseOk = $true
    if ($localExists) {
        try {
            $localText = Get-Content -LiteralPath $Local -Raw -Encoding UTF8
            $localObj = $localText | ConvertFrom-Json
            $localRead = Read-RecordSet $localObj
            if ($localRead.Ok) { $localRecords = @($localRead.Records) } else { $localParseOk = $false }
        } catch {
            $localParseOk = $false
        }
    }

    # ---- 步骤 5（先算）：差异报告 ----
    $cloudKeys = @{}
    foreach ($r in $cloudRecords) { $cloudKeys[(Get-TripleKey $r)] = $true }

    $localOnly = New-Object System.Collections.ArrayList
    $seenLocal = @{}
    foreach ($r in $localRecords) {
        $k = Get-TripleKey $r
        if ($cloudKeys.ContainsKey($k)) { continue }
        if ($seenLocal.ContainsKey($k)) { continue }
        $seenLocal[$k] = $true
        [void]$localOnly.Add($r)
    }

    Write-Output ''
    Write-Output '[5/5] 差异报告'
    Write-Output ('-' * 68)
    Write-Output ("  本地条数（同步前）: {0}" -f $localRecords.Count)
    Write-Output ("  云端条数（同步后）: {0}" -f $cloudRecords.Count)
    if (-not $localExists) {
        Write-Output '  （本地文件原先不存在，将直接创建）'
    } elseif (-not $localParseOk) {
        Write-Output '  【警告】本地文件无法解析为合法 schema，差异比对不可靠；仍会先备份再覆盖。'
    }
    Write-Output ("  本地有而云端没有（同步后会被丢弃）: {0} 条" -f $localOnly.Count)
    if ($localOnly.Count -gt 0) {
        Write-Output '  --- 将被丢弃的记录明细（company · title · date）---'
        $i = 0
        foreach ($r in $localOnly) {
            $i++
            $co = ([string](Get-Field $r 'company')).Trim()
            $ti = ([string](Get-Field $r 'title')).Trim()
            $dt = Get-TripleDate $r
            $id = [string](Get-Field $r 'id')
            Write-Output ("    {0,3}. {1} · {2} · {3}   [id={4}]" -f $i, $co, $ti, $dt, $id)
        }
    } else {
        Write-Output '  （无：本地每一条都能在云端找到对应记录）'
    }
    Write-Output ('-' * 68)

    if ($DryRun) {
        Write-Output ''
        Write-Output '[DRY-RUN] 未写入本地文件，未做备份。如需真实同步，去掉 -DryRun 再运行一次。'
        Write-Output '结果：OK'
        exit 0
    }

    # ---- 步骤 3：备份本地 ----
    Write-Output ''
    Write-Output '[3/5] 备份本地 ...'
    if ($localExists) {
        $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
        $backup = "$Local.bak_sync_$stamp"
        Copy-Item -LiteralPath $Local -Destination $backup -Force
        Write-Output ("      已备份 -> {0}" -f $backup)
    } else {
        Write-Output '      本地文件不存在，跳过备份。'
    }

    # ---- 步骤 4：原子覆盖本地为云端版本 ----
    Write-Output '[4/5] 覆盖本地为云端版本（原子替换）...'
    $tmpWrite = "$Local.sync_tmp_$([guid]::NewGuid().ToString('N'))"
    Copy-Item -LiteralPath $tmpCloud -Destination $tmpWrite -Force
    # 关键：不能用 Move-Item -Force 覆盖已存在目标 —— 实测它是「逐字节复制」（1GB≈724ms，
    # 随体积线性增长），中断会在「最终路径」留下半截文件。改用 .NET 原语：
    #   目标已存在 → [System.IO.File]::Replace()：底层 MoveFileEx(REPLACE_EXISTING|WRITE_THROUGH)，
    #               同卷元数据级原子替换，不做数据拷贝；
    #   目标不存在 → [System.IO.File]::Move()：纯 rename，天然原子。
    # 两者保证最终路径任意时刻要么是旧完整文件、要么是新完整文件，绝无半截。
    # 注意：第 3 参（备份文件名）必须用 [NullString]::Value 传真 null —— 直接写 $null 会被
    # PowerShell 强转成空字符串 ""，导致 Replace 抛「路径的形式不合法」（已实测踩坑）。
    if (Test-Path -LiteralPath $Local) {
        [System.IO.File]::Replace($tmpWrite, $Local, [NullString]::Value, $true)
    } else {
        [System.IO.File]::Move($tmpWrite, $Local)
    }
    $tmpWrite = $null

    # ---- 收尾校验 ----
    $afterText = Get-Content -LiteralPath $Local -Raw -Encoding UTF8
    $afterObj = $afterText | ConvertFrom-Json
    $afterRead = Read-RecordSet $afterObj
    if (-not $afterRead.Ok) { throw ('同步后本地文件 schema 异常：{0}' -f $afterRead.Reason) }
    $afterCount = @($afterRead.Records).Count
    if ($afterCount -ne $cloudRecords.Count) {
        throw ("同步后条数不一致：本地 {0} vs 云端 {1}" -f $afterCount, $cloudRecords.Count)
    }
    Write-Output ("      同步完成：本地记录数 = {0}（与云端一致）" -f $afterCount)
    Write-Output ''
    Write-Output '结果：OK（已同步）'
    exit 0
}
catch {
    Write-Output ''
    Write-Output ('结果：FAILED - ' + $_.Exception.Message)
    [Console]::Error.WriteLine(('sync_from_cloud.ps1 失败: ' + $_.Exception.Message))
    exit 1
}
finally {
    if (Test-Path -LiteralPath $tmpCloud) { Remove-Item -LiteralPath $tmpCloud -Force -ErrorAction SilentlyContinue }
    if ($tmpWrite -and (Test-Path -LiteralPath $tmpWrite)) { Remove-Item -LiteralPath $tmpWrite -Force -ErrorAction SilentlyContinue }
}
