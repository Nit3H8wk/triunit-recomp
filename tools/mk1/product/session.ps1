[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ProjectRoot,[string]$DataRoot='',
      [ValidateRange(0,500000)][int]$WindowFrames=0,[string]$PlanOutput='',
      [ValidateSet('original','presentation')][string]$VisualMode='original',
      [ValidateSet('original','remastered')][string]$GameMode='original',
      [ValidateRange(0,1)][double]$Scanlines=0,
      [ValidateRange(0,100)][int]$ScaleFX=0,
      [ValidateSet('nearest','linear','sharp-bilinear','bicubic')][string]$Filter='nearest',
      [ValidateRange(0,5)][int]$ScaleMode=0,
      [ValidateRange(0,100)][int]$Cas=0,[ValidateRange(0,100)][int]$Bilateral=0,
      [ValidateSet(0,1)][int]$Smaa=0,[ValidateSet(0,1)][int]$GameFullscreen=1,
      [ValidateSet('off','bvm-1080','bvm-4k','bvm-soft','energy','pvm','phosphor')][string]$CrtPreset='off',
      [ValidateSet('vsync','vrr','immediate')][string]$SyncMode='vrr',
      [ValidateSet('original','vivid','warm')][string]$ColorMode='original',
      [ValidateSet(80,90,100,110,120)][int]$Brightness=100,
      [ValidateSet(0,1)][int]$Bezel=1,[ValidateSet(0,1)][int]$HighRefresh=0,
      [ValidateSet('low','balanced','safe')][string]$AudioLatency='balanced',
      [ValidateRange(0,100)][int]$GameVolume=100,
      [ValidateSet(65279,48895,32511,16127)][int]$DswWord=65279,
      [ValidateSet(0,1)][int]$CmosCoinage=0)
$ErrorActionPreference='Stop'
$env:PSModulePath=[IO.Path]::Combine($PSHOME,'Modules')
$utf8=New-Object Text.UTF8Encoding($false)
function Write-Json([string]$Path,$Value){Assert-Unlinked $Path;[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 16)+[Environment]::NewLine,$utf8)}
function Assert-Unlinked([string]$Path){
    $cursor=[IO.Path]::GetFullPath($Path)
    while($cursor){if([IO.File]::Exists($cursor)-or[IO.Directory]::Exists($cursor)){if(([IO.File]::GetAttributes($cursor)-band[IO.FileAttributes]::ReparsePoint)-ne 0){throw 'Caminho de sessao nao aceita links ou junctions.'}}
        $parent=[IO.Path]::GetDirectoryName($cursor);if($parent-eq$cursor){break};$cursor=$parent}
}
function Hash([string]$Path){Assert-Unlinked $Path;$f=[IO.File]::OpenRead($Path);$a=[Security.Cryptography.SHA256]::Create();try{return [BitConverter]::ToString($a.ComputeHash($f)).Replace('-','').ToLowerInvariant()}finally{$a.Dispose();$f.Dispose()}}
function Quote-Argument([string]$Value){'"'+$Value.Replace('"','\"').TrimEnd('\')+'"'}
function Read-Live([string]$Path){
    $f=$null;$reader=$null
    try{$f=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite);$reader=New-Object IO.StreamReader($f,$utf8);$text=$reader.ReadToEnd();if($text.Length-gt4096){return $null};return ($text|ConvertFrom-Json)}
    catch{return $null}finally{if($reader){$reader.Dispose()}elseif($f){$f.Dispose()}}
}
function Write-Raw([string]$Path,[string]$Text){Assert-Unlinked $Path;$b=$utf8.GetBytes($Text);$count=[Math]::Min($b.Length,65536);$tail=New-Object byte[] $count;if($count){[Array]::Copy($b,$b.Length-$count,$tail,0,$count)};[IO.File]::WriteAllBytes($Path,$tail);return ($b.Length-gt65536)}
function Write-Text([string]$Path,[string]$Text){Assert-Unlinked $Path;[IO.File]::WriteAllText($Path,$Text,$utf8)}
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
Assert-Unlinked $ProjectRoot;Assert-Unlinked $PSScriptRoot
if($VisualMode-eq'original'){$Scanlines=0;$Filter='nearest';$CrtPreset='off'}
if($CrtPreset-ne'off'){$Scanlines=0}
$env:MK1_SYNC=$SyncMode
$env:MK1_COLOR=$ColorMode
$env:MK1_BRIGHTNESS="$Brightness"
$env:MK1_BEZEL="$Bezel"
$env:MK1_HIGH_REFRESH="$HighRefresh"
$env:MK1_FULLSCREEN="$GameFullscreen"
$env:MK1_MUSIC_MODE=$GameMode
$env:MK1_MUSIC_DIRECTORY=Join-Path $ProjectRoot 'custom_audio/mk1'
$env:MK1_AUDIO_LATENCY=$AudioLatency
$env:MK1_GAME_VOLUME="$GameVolume"
$env:MK1_CRT_PRESET=$CrtPreset
$env:MK1_SCANLINES=$Scanlines.ToString([Globalization.CultureInfo]::InvariantCulture)
$env:MK1_FILTER=$Filter
$env:MK1_SCALEFX="$ScaleFX"
$env:MK1_SCALE_MODE="$ScaleMode"
$env:MK1_CAS="$Cas"
$env:MK1_BILATERAL="$Bilateral"
$env:MK1_SMAA="$Smaa"
$visual=[ordered]@{game_mode=$GameMode;renderer='D3D12-DXGI-flip';mode=$VisualMode;scanlines=$Scanlines;scalefx=$ScaleFX;filter=$Filter;scale_mode=$ScaleMode;cas=$Cas;bilateral=$Bilateral;smaa=$Smaa;fullscreen=$GameFullscreen;crt_preset=$CrtPreset;sync=$SyncMode;color=$ColorMode;brightness=$Brightness;bezel=$Bezel;high_refresh=$HighRefresh;audio_latency=$AudioLatency;source_resolution='400x254';dlss_available=$false;internal_resolution_scaling_available=$false}
$engine=Join-Path $PSScriptRoot 'mk5-native-audio.exe';$seed=Join-Path $PSScriptRoot 'factory-default-control-input.bin'
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw|ConvertFrom-Json
foreach($file in $manifest.files.PSObject.Properties){if($file.Name-ne[IO.Path]::GetFileName($file.Name)){throw 'Manifesto invalido.'};if((Hash(Join-Path $PSScriptRoot $file.Name))-ne$file.Value){throw ('Integridade incorreta: '+$file.Name)}}
if((Hash $engine)-ne'@@ENGINE_SHA256@@'){throw 'Motor diferente da versao temporaria 8.'}
$roms=Join-Path $ProjectRoot 'roms'
foreach($rom in $manifest.roms_required){$path=Join-Path $roms $rom.path;if(!(Test-Path -LiteralPath $path -PathType Leaf)-or(Get-Item -LiteralPath $path).Length-ne$rom.size-or(Hash $path)-ne$rom.sha256){throw ('ROM ausente ou diferente: '+$rom.path)}}
if($DataRoot){Assert-Unlinked $DataRoot;$logs=Join-Path $DataRoot 'logs';$profile=Join-Path $DataRoot 'profile'}
else{$logs=Join-Path $ProjectRoot 'logs/temporaria-8';$profile=Join-Path $ProjectRoot 'build/native/manual-temporary-8-20261025/profile'}
Assert-Unlinked $logs;Assert-Unlinked $profile
$nativeArgs=@('--roms',$roms,'--stage','visual','--window-frames',"$WindowFrames",'--irq-pending','0x400','--raster-next-line','1','--raster-quanta','6325','--body-sound-status-byte','128')
$effectiveDsw=$DswWord
if($CmosCoinage){$effectiveDsw=$effectiveDsw-band0xff7f}
$combinedDsw=([uint32]$effectiveDsw*65536)+65535
foreach($prefix in @('','boot-','task-','body-','main-')){$nativeArgs+=@("--${prefix}dsw-word","$effectiveDsw")}
foreach($prefix in @('','body-','active-')){$nativeArgs+=@("--${prefix}irq-in01",'0xffffffff',"--${prefix}irq-in2-dsw","$combinedDsw")}
$plannedArgs=$nativeArgs+@('--cmos-input','<perfil CMOS original de 16 KB>','--cmos-output','<saida CMOS exclusiva>','--live-status','<arquivo vivo de estado, sobrescrito>')
if($PlanOutput){Assert-Unlinked $PlanOutput;Write-Json $PlanOutput ([ordered]@{version='temporaria-8';window_frames=$WindowFrames;unlimited_session=($WindowFrames-eq0);engine_sha256=(Hash $engine);arguments=$plannedArgs;presentation=$visual;logs=$logs;profile=$profile;logging_max_bytes_per_session=6291456;poll_interval_ms=250;game_rules_changed=$false});exit 0}
[IO.Directory]::CreateDirectory($logs)|Out-Null;[IO.Directory]::CreateDirectory($profile)|Out-Null
$id='sessao-'+[DateTime]::Now.ToString('yyyyMMdd-HHmmss')+'-'+$PID+'-'+[guid]::NewGuid().ToString('N').Substring(0,6)
$session=Join-Path $logs $id;[IO.Directory]::CreateDirectory($session)|Out-Null
$livePath=Join-Path $session 'live.json';$pending=Join-Path $profile ('cmos-pending-'+[guid]::NewGuid().ToString('N')+'.bin')
$current=Join-Path $profile 'cmos.bin';$lock=$null;$events=$null;$timeline=$null;$process=$null;$processStarted=$false
$clock=[Diagnostics.Stopwatch]::StartNew();$started=[DateTime]::UtcNow.ToString('o')
$summary=[ordered]@{version='temporaria-8';session_id=$id;started_utc=$started;presentation_settings=$visual;exit_code=$null;child_exit_code=$null;logger_failed=$false;finalization_errors=@();engine_sha256=(Hash $engine);cmos_committed=$false;recovery_path=$null;game=$null;audio=$null;last_state=$null;error=$null;logging_scope='Periodic original state, transitions, stdout/stderr; no video, PCM, memory dump or input replay.'}
try{
    $lockPath=Join-Path $profile 'session.lock';Assert-Unlinked $lockPath
    $lock=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $cmosInput=$seed;if([IO.File]::Exists($current)){Assert-Unlinked $current;if((Get-Item -LiteralPath $current).Length-ne16384){throw 'CMOS do perfil deve ter 16 KB.'};$cmosInput=$current}
    Add-Type -Path (Join-Path $PSScriptRoot 'LogStore.dll')
    $events=New-Object Mk1BoundedLog($session,'events',1048576,1)
    $timeline=New-Object Mk1BoundedLog($session,'timeline',2097152,2)
    $engineArgs=$nativeArgs+@('--cmos-input',$cmosInput,'--cmos-output',$pending,'--live-status',$livePath)
    Write-Json (Join-Path $session 'session.json') ([ordered]@{version='temporaria-8';started_utc=$started;engine=$engine;engine_sha256=$summary.engine_sha256;arguments=$engineArgs;cmos_input_sha256=(Hash $cmosInput);cmos_input_bytes=(Get-Item -LiteralPath $cmosInput).Length;sampling_ms=250;timeline_slots=2;timeline_slot_bytes=2097152;events_limit_bytes=1048576;rules_changed=$false})
    Write-Text (Join-Path $logs 'ULTIMA-SESSAO.txt') "EM ANDAMENTO`r`n$session`r`n"
    $null=$events.Write((@{event='session-start';utc=$started;engine_sha256=$summary.engine_sha256}|ConvertTo-Json -Compress))
    $info=New-Object Diagnostics.ProcessStartInfo;$info.FileName=$engine;$info.Arguments=(($engineArgs|ForEach-Object {Quote-Argument $_})-join' ');$info.WorkingDirectory=$ProjectRoot;$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.StandardOutputEncoding=$utf8;$info.StandardErrorEncoding=$utf8
    $process=New-Object Diagnostics.Process;$process.StartInfo=$info;if(!$process.Start()){throw 'Nao foi possivel iniciar o jogo.'};$processStarted=$true
    $stdoutTask=$process.StandardOutput.ReadToEndAsync();$stderrTask=$process.StandardError.ReadToEndAsync()
    $summary.child_pid=$process.Id;$lastSignature='';$lastFrame=-1;$lastProgressMs=0;$stalled=$false
    while(!$process.WaitForExit(250)){
        $s=Read-Live $livePath;if(!$s){continue}
        $summary.last_state=$s;$ms=$clock.ElapsedMilliseconds
        if($s.scanout_frame-ne$lastFrame){if($stalled){$null=$events.Write((@{event='frame-resumed';elapsed_ms=$ms;frame=$s.scanout_frame}|ConvertTo-Json -Compress));$stalled=$false};$lastFrame=$s.scanout_frame;$lastProgressMs=$ms}
        elseif(!$stalled-and$ms-$lastProgressMs-ge3000){$null=$events.Write((@{event='frame-stall-observed';elapsed_ms=$ms;state=$s}|ConvertTo-Json -Depth 6 -Compress));$stalled=$true}
        $sig=@($s.mode,$s.p1,$s.p2,$s.fighter1,$s.fighter2,$s.round_wins1,$s.round_wins2,$s.winner,$s.tower_slot,$s.credits,$s.presentation.exclusive,$s.presentation.mode_errors)-join','
        if($sig-ne$lastSignature){$null=$events.Write((@{event='game-transition';elapsed_ms=$ms;state=$s}|ConvertTo-Json -Depth 6 -Compress));$lastSignature=$sig}
        try{if($process.HasExited){continue};$process.Refresh();$cpuMs=[long]$process.TotalProcessorTime.TotalMilliseconds;$workingSet=$process.WorkingSet64}catch{continue}
        $null=$timeline.Write((@{elapsed_ms=$ms;cpu_ms=$cpuMs;working_set_bytes=$workingSet;state=$s}|ConvertTo-Json -Depth 6 -Compress))
    }
    $process.WaitForExit();$summary.child_exit_code=$process.ExitCode;$summary.exit_code=$process.ExitCode
    $stdout=$stdoutTask.GetAwaiter().GetResult();$stderr=$stderrTask.GetAwaiter().GetResult()
    $summary.stdout_truncated=Write-Raw (Join-Path $session 'stdout.log') $stdout;$summary.stderr_truncated=Write-Raw (Join-Path $session 'stderr.log') $stderr
    foreach($line in ($stdout-split"`r?`n")){if(!$line.StartsWith('{')){continue};try{$v=$line|ConvertFrom-Json}catch{continue};if($v.scope-eq'mk5-visual'){$summary.game=$v};if($v.audio){$summary.audio=$v}}
    $final=Read-Live $livePath;if($final){$summary.last_state=$final}
    if($summary.exit_code-eq0-and$summary.game-and$summary.game.cmos_saved-and$summary.game.stop-in@('window-closed','window-frame-limit')){
        if(!(Test-Path -LiteralPath $pending)-or(Get-Item -LiteralPath $pending).Length-ne16384-or(Hash $pending)-ne$summary.game.live_cmos_sha256){throw 'Saida CMOS nao coincide com o estado vivo informado pelo jogo.'}
        if([IO.File]::Exists($current)){[IO.File]::Replace($pending,$current,[NullString]::Value)}else{[IO.File]::Move($pending,$current)};$summary.cmos_committed=$true
    }
}catch{
    $summary.error=$_.Exception.Message;$summary.logger_failed=$true;$summary.exit_code=4
    # Logger failure must never terminate an ongoing human game.
    if($processStarted){
        try{$process.WaitForExit();$summary.child_exit_code=$process.ExitCode}catch{$summary.finalization_errors+=('wait: '+$_.Exception.Message)}
        try{if($stdoutTask){$null=Write-Raw (Join-Path $session 'stdout.log') $stdoutTask.GetAwaiter().GetResult()}}catch{$summary.finalization_errors+=('stdout: '+$_.Exception.Message)}
        try{if($stderrTask){$null=Write-Raw (Join-Path $session 'stderr.log') $stderrTask.GetAwaiter().GetResult()}}catch{$summary.finalization_errors+=('stderr: '+$_.Exception.Message)}
    }
}finally{
    try{
        $summary.ended_utc=[DateTime]::UtcNow.ToString('o');$summary.wall_seconds=$clock.Elapsed.TotalSeconds
        if([IO.File]::Exists($pending)){$summary.recovery_path=$pending}
        if($events){
            try{$summary.event_records_dropped=$events.Dropped;$null=$events.Write((@{event='session-end';exit_code=$summary.exit_code;child_exit_code=$summary.child_exit_code;error=$summary.error;elapsed_ms=$clock.ElapsedMilliseconds}|ConvertTo-Json -Compress))}catch{$summary.finalization_errors+=('events: '+$_.Exception.Message)}
            try{$events.Dispose()}catch{$summary.finalization_errors+=('events-dispose: '+$_.Exception.Message)}
        }
        if($timeline){
            try{$summary.timeline_rotations=$timeline.Rotations;$summary.timeline_records_dropped=$timeline.Dropped}catch{$summary.finalization_errors+=('timeline-stats: '+$_.Exception.Message)}
            try{$timeline.Dispose()}catch{$summary.finalization_errors+=('timeline-dispose: '+$_.Exception.Message)}
        }
        if($summary.finalization_errors.Count){$summary.logger_failed=$true;$summary.exit_code=4}
        try{Write-Json (Join-Path $logs 'latest.json') ([ordered]@{session=$session;summary=(Join-Path $session 'summary.json');exit_code=$summary.exit_code;ended_utc=$summary.ended_utc})}catch{$summary.finalization_errors+=('latest: '+$_.Exception.Message)}
        try{Write-Text (Join-Path $logs 'ULTIMA-SESSAO.txt') "ENCERRADA`r`n$session`r`nCodigo: $($summary.exit_code)`r`n"}catch{$summary.finalization_errors+=('last-session: '+$_.Exception.Message)}
        if($summary.finalization_errors.Count){$summary.logger_failed=$true;$summary.exit_code=4}
        try{Write-Json (Join-Path $session 'summary.json') $summary}catch{$summary.logger_failed=$true;$summary.exit_code=4;[Console]::Error.WriteLine('Falha ao gravar summary.json: '+$_.Exception.Message)}
    }finally{
        try{if($lock){$lock.Dispose()}}finally{if($process){$process.Dispose()}}
    }
}
exit $summary.exit_code
